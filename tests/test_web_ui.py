"""网页界面：接口行为、本机访问限制、后台推导任务，全部离线（MockRunner），不碰真实 .env。"""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from blueprint import providers
from blueprint.llm import BudgetExceeded
from blueprint.web.jobs import JobManager, friendly_error
from blueprint.web.server import App, create_server
from blueprint.web.views import list_products, product_detail, resolve_workspace

ROOT = Path(__file__).resolve().parents[1]
IDEA = "家长拍一张玩具合影，AI 生成亲子剧情脚本。照片涉及隐私，默认不保存。生成内容必须过适龄审核。"


def clear_env(monkeypatch, *names):
    """先 setenv 再 delenv：保证测试里写进 os.environ 的配置在结束后被撤销（delenv 不记录本来就不存在的变量）。"""
    for name in names or ("ANTHROPIC_API_KEY", "MODEL_ID", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def wait_job(job, timeout=10):
    deadline = time.time() + timeout
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    return job


@pytest.fixture
def app(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    return App(tmp_path / "out", env_path=tmp_path / ".env", mock=True)


@pytest.fixture
def server(app):
    srv = create_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


# -- App：产品与推导 ------------------------------------------------------------

def test_create_product_runs_plan_in_background_and_logs_iteration(app):
    res = app.create_product({"name": "玩具剧场", "idea": IDEA})
    job = wait_job(app.jobs.get(res["job"]["id"]))
    assert job.status == "done", job.error
    assert any("① 需求拆解" in line for line in job.logs)
    ws = app.out_root / res["slug"]
    assert (ws / "plan.json").is_file() and (ws / "方案.md").is_file()
    assert "方案推导" in (ws / "迭代记录.md").read_text(encoding="utf-8")

    detail = app.product(res["slug"])
    assert detail["name"] == "玩具剧场" and detail["version"] == 1
    assert detail["job"]["status"] == "done"
    plan = detail["plan"]
    assert len(plan["components"]) == 17 and len(plan["layers"]) == 7
    assert plan["unknowns"] and all(isinstance(q, str) for q in plan["unknowns"])
    assert {f["label"] for f in plan["facts"]} >= {"目标", "用户"}


def test_duplicate_product_name_gets_plain_message(app):
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    with pytest.raises(ValueError, match="换个名字"):
        app.create_product({"name": "玩具剧场", "idea": "另一个想法"})


def test_one_running_job_per_product():
    jobs = JobManager()
    gate = threading.Event()
    jobs.start("plan", "p", lambda log: gate.wait(5))
    with pytest.raises(ValueError, match="正在推导中"):
        jobs.start("plan", "p", lambda log: None)
    gate.set()


def test_failed_job_keeps_friendly_error():
    jobs = JobManager()

    def boom(log):
        log("  ▶ ① 需求拆解")
        raise BudgetExceeded("已达到调用次数上限 16")

    job = wait_job(jobs.start("plan", "p", boom))
    assert job.status == "failed" and "继续推导" in job.error
    assert job.logs[-1].startswith("✗")


def test_friendly_error_maps_sdk_errors_by_name():
    AuthenticationError = type("AuthenticationError", (Exception,), {})
    InternalServerError = type("InternalServerError", (Exception,), {"status_code": 502})
    assert "API Key" in friendly_error(AuthenticationError("401"))
    assert "不是你的问题" in friendly_error(InternalServerError("502"))


def test_real_mode_requires_configured_key(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    app = App(tmp_path / "out", env_path=tmp_path / ".env", mock=False)
    assert not app.configured()
    with pytest.raises(ValueError, match="配置模型"):
        app.create_product({"name": "x", "idea": "y"})
    assert not (tmp_path / "out" / "x").exists()


def test_save_settings_tests_connection_and_keeps_other_env_lines(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=old\nBLUEPRINT_MAX_OUTPUT_TOKENS=32000\n", encoding="utf-8")
    monkeypatch.setattr(providers, "test_connection", lambda base, key, model: (True, "连接成功"))
    app = App(tmp_path / "out", env_path=env)

    res = app.save_settings({"provider": "deepseek", "api_key": "sk-real-0123456789"})
    assert res["ok"]
    saved = providers.read_env(env)
    assert saved["ANTHROPIC_API_KEY"] == "sk-real-0123456789"
    assert saved["MODEL_ID"] == "deepseek-v4-flash"
    assert saved["BLUEPRINT_MAX_OUTPUT_TOKENS"] == "32000"
    settings = app.settings()
    assert settings["configured"] and settings["provider"] == "deepseek"
    assert "0123456789" not in json.dumps(settings)          # 页面只拿到掩码

    # 不填 Key 表示沿用已保存的
    monkeypatch.setattr(providers, "test_connection", lambda base, key, model: (key == "sk-real-0123456789", "x"))
    assert app.save_settings({"provider": "anthropic", "api_key": ""})["ok"]
    assert "ANTHROPIC_BASE_URL" not in providers.read_env(env)


def test_failed_connection_does_not_write_env(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setattr(providers, "test_connection", lambda base, key, model: (False, "连接失败：401"))
    app = App(tmp_path / "out", env_path=tmp_path / ".env")
    assert not app.save_settings({"provider": "glm", "api_key": "sk-real-0123456789"})["ok"]
    assert not (tmp_path / ".env").exists()


# -- views ---------------------------------------------------------------------

def test_resolve_workspace_rejects_paths_outside_out_root(app):
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    assert resolve_workspace(app.out_root, "玩具剧场").name == "玩具剧场"
    for bad in ("..", "../out", ".hidden", "a/b", "a\\b", "", "不存在"):
        with pytest.raises(LookupError):
            resolve_workspace(app.out_root, bad)


def test_list_products_without_plan(tmp_path):
    from blueprint.workspace import init_workspace
    init_workspace(tmp_path, "只有点子", "一个想法")
    [p] = list_products(tmp_path)
    assert p["name"] == "只有点子" and not p["has_plan"] and p["unknowns"] == 0
    assert product_detail(tmp_path / "只有点子")["plan"] is None
    assert list_products(tmp_path / "missing") == []


# -- HTTP ----------------------------------------------------------------------

def test_http_end_to_end(server):
    _srv, base = server
    status, body, headers = call(base + "/")
    assert status == 200 and b"Agent Blueprint" in body and "text/html" in headers["Content-Type"]
    script = re.search(rb'src="(/static/assets/[^"]+\.js)"', body).group(1).decode()
    status, _, headers = call(base + script)
    assert status == 200 and "javascript" in headers["Content-Type"]

    status, body, _ = call(base + "/api/products", {"name": "玩具剧场", "idea": IDEA})
    assert status == 201
    created = json.loads(body)
    for _ in range(200):
        job = json.loads(call(f"{base}/api/jobs/{created['job']['id']}")[1])
        if job["status"] != "running":
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    slug = urllib.request.quote(created["slug"])
    detail = json.loads(call(f"{base}/api/products/{slug}")[1])
    assert detail["plan"]["title"]
    assert json.loads(call(base + "/api/products")[1])["products"][0]["slug"] == "玩具剧场"


def test_http_rejects_foreign_host_origin_and_form_posts(server):
    _srv, base = server
    assert call(base + "/api/products", headers={"Host": "evil.example"})[0] == 403
    assert call(base + "/api/products", {"name": "x", "idea": "y"}, {"Origin": "http://evil.example"})[0] == 403
    req = urllib.request.Request(base + "/api/products", data=b"name=x&idea=y", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 415


def test_http_static_and_api_404s(server):
    _srv, base = server
    assert call(base + "/static/..%2Fserver.py")[0] == 404
    assert call(base + "/static/assets/..%2F..%2Fserver.py")[0] == 404
    assert call(base + "/static/nope.js")[0] == 404
    assert call(base + "/api/products/..%2F..%2Fetc")[0] == 404
    assert call(base + "/api/jobs/999")[0] == 404
    status, body, _ = call(base + "/api/products", {"name": "", "idea": ""})
    assert status == 400 and json.loads(body)["error"]


def test_student_package_ships_web_ui():
    import importlib.util
    spec = importlib.util.spec_from_file_location("package_student", ROOT / "tools/package_student.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = {p.relative_to(ROOT).as_posix() for p in mod.collect_files(ROOT)}
    assert {"启动界面.command", "tools/mac_env.sh", "blueprint/web/server.py", "blueprint/chat.py",
            "blueprint/web/static/index.html", "blueprint/knowledge/prompts/chat_system.md"} <= names
    assert any(n.startswith("blueprint/web/static/assets/") and n.endswith(".js") for n in names)
    assert not any(n.startswith("web/") for n in names)        # 前端源码和 node_modules 不进学生包


# -- 对话 ----------------------------------------------------------------------

def stream(base, path, messages):
    req = urllib.request.Request(base + path, data=json.dumps({"messages": messages}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        assert res.headers["Content-Type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in res.read().decode().splitlines() if line.strip()]


def test_intake_chat_asks_three_rounds_then_drafts(server):
    from blueprint.chat import FINISH_INTAKE, INTAKE_ROUNDS
    _srv, base = server
    conv = [{"role": "user", "text": IDEA}]
    for _ in INTAKE_ROUNDS:
        events = stream(base, "/api/chat/intake", conv)
        text = "".join(e["delta"] for e in events if e["type"] == "text")
        assert text and events[-1] == {"type": "done"}
        assert any(e["type"] == "suggestions" and FINISH_INTAKE in e["items"] for e in events)
        conv += [{"role": "assistant", "text": text}, {"role": "user", "text": "给家长用"}]
    events = stream(base, "/api/chat/intake", conv)
    [tool] = [e for e in events if e["type"] == "tool"]
    assert tool["name"] == "confirm_product" and tool["args"]["name"] and "给家长用" in tool["args"]["idea"]


def test_intake_chat_can_finish_early_and_reports_errors_in_stream(server):
    from blueprint.chat import FINISH_INTAKE
    _srv, base = server
    events = stream(base, "/api/chat/intake", [{"role": "user", "text": IDEA}, {"role": "assistant", "text": "q"},
                                               {"role": "user", "text": FINISH_INTAKE}])
    assert [e["name"] for e in events if e["type"] == "tool"] == ["confirm_product"]
    events = stream(base, "/api/chat/intake", [{"role": "user", "text": "  "}])
    assert events[0]["type"] == "error" and events[-1]["type"] == "done"


def test_chat_requires_configured_model(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    app = App(tmp_path / "out", env_path=tmp_path / ".env")
    with pytest.raises(ValueError, match="配置模型"):
        app.intake_chat({"messages": [{"role": "user", "text": "x"}]})


def test_answer_chat_walks_questions_and_saves_into_prd(app):
    from blueprint.chat import HELP, SAVE, SKIP
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    detail = app.product("玩具剧场")
    questions = detail["plan"]["unknowns"]
    assert len(questions) >= 3 and questions[0] in detail["answer_intro"]

    def turn(conv):
        events = list(app.answer_chat("玩具剧场", {"messages": conv}))
        conv.append({"role": "assistant", "text": "".join(e["delta"] for e in events if e["type"] == "text")})
        return events

    conv = [{"role": "assistant", "text": detail["answer_intro"]}, {"role": "user", "text": "6 到 8 岁"}]
    assert "第 2 /" in turn(conv)[0]["delta"]
    conv.append({"role": "user", "text": HELP})
    turn(conv)
    assert "B." in conv[-1]["text"]
    conv.append({"role": "user", "text": "b"})                 # 回一个字母 → 记下选项原文
    turn(conv)
    conv.append({"role": "user", "text": SKIP})
    turn(conv)
    conv.append({"role": "user", "text": SAVE})
    [tool] = [e for e in turn(conv) if e["type"] == "tool"]
    answers = tool["args"]["answers"]
    assert [a["question"] for a in answers] == questions[:2]
    assert answers[0]["answer"] == "6 到 8 岁" and answers[1]["answer"].startswith("第一版就做完整")

    job = wait_job(app.jobs.get(app.save_answers("玩具剧场", {"answers": answers})["job"]["id"]))
    assert job.status == "done", job.error
    prd = (app.out_root / "玩具剧场" / "PRD.md").read_text(encoding="utf-8")
    section = prd.split("## 6. 待确认问题与回答", 1)[1].split("\n## ", 1)[0]
    assert "**答**：6 到 8 岁" in section and questions[0] in section
    assert "回答待确认问题" in (app.out_root / "玩具剧场" / "迭代记录.md").read_text(encoding="utf-8")


def test_save_answers_rejects_empty(app):
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    with pytest.raises(ValueError, match="没有可保存"):
        app.save_answers("玩具剧场", {"answers": [{"question": "q", "answer": "  "}]})
