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


# -- 交接包与大白话问题 -----------------------------------------------------------

def test_handoff_download_over_http(server, app):
    _srv, base = server
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    status, body, headers = call(f"{base}/api/products/{urllib.request.quote('玩具剧场')}/handoff")
    assert status == 200 and headers["Content-Type"] == "application/zip"
    assert "filename*=UTF-8''" + urllib.request.quote("玩具剧场-交接包-V1.zip") in headers["Content-Disposition"]
    import io
    import zipfile
    assert "玩具剧场-交接包/交接说明.md" in zipfile.ZipFile(io.BytesIO(body)).namelist()


def test_handoff_without_plan_is_a_plain_400(server, app):
    from blueprint.workspace import init_workspace
    _srv, base = server
    init_workspace(app.out_root, "只有点子", "一个想法")
    status, body, _ = call(f"{base}/api/products/{urllib.request.quote('只有点子')}/handoff")
    assert status == 400 and "还没有方案" in json.loads(body)["error"]


def test_plan_job_splits_questions_and_answers_keep_original(app):
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    plan = app.product("玩具剧场")["plan"]
    assert plan["unknowns"] == [q["text"] for q in plan["questions"]]
    assert isinstance(plan["dev_items"], list)
    comp = next(q for q in plan["questions"] if q.get("component"))
    assert comp["text"] != comp["original"] and "（关系到组件" in comp["text"]

    job = wait_job(app.jobs.get(app.save_answers("玩具剧场", {"answers": [{"question": comp["text"], "answer": "不需要"}]})["job"]["id"]))
    assert job.status == "done", job.error
    prd = (app.out_root / "玩具剧场" / "PRD.md").read_text(encoding="utf-8")
    assert f"（原问题：{comp['original']}）" in prd and "**答**：不需要" in prd


# -- 加新需求与版本历史 -----------------------------------------------------------

def test_revise_job_returns_diff_and_history_tracks_versions(server, app):
    _srv, base = server
    wait_job(app.jobs.get(app.create_product({"name": "邮件助手", "idea": "每天整理我的邮箱，挑出要回复的"})["job"]["id"]))
    slug = urllib.request.quote("邮件助手")
    events = stream(base, f"/api/products/{slug}/revise-chat", [{"role": "user", "text": "删除邮件前要我确认，并留记录"}])
    assert any(e["type"] == "suggestions" for e in events)

    job = wait_job(app.start_revise("邮件助手", {"title": "删除前确认并留痕", "requirement": "删除邮件前要我确认，每次删除都留记录"}))
    assert job.status == "done", job.error
    assert job.result["old_version"] == 1 and job.result["new_version"] == 2
    assert all({"id", "name", "before", "after"} <= set(d) for d in job.result["diff"])
    assert json.loads(call(f"{base}/api/jobs/{job.id}")[1])["result"]["new_version"] == 2

    history = json.loads(call(f"{base}/api/products/{slug}/history")[1])
    assert history["current"] == 2 and history["snapshots"] == [1]
    assert history["versions"][-1] == {"version": 2, "date": history["versions"][-1]["date"],
                                       "change": "删除前确认并留痕", "source": "网页界面·加新需求"}
    assert [e["title"] for e in history["log"]][-1] == "新需求"

    v1 = json.loads(call(f"{base}/api/products/{slug}/prd?v=1")[1])
    now = json.loads(call(f"{base}/api/products/{slug}/prd")[1])
    assert not v1["current"] and "删除邮件前" not in v1["text"]
    assert now["current"] and now["version"] == 2 and "删除邮件前" in now["text"]
    assert call(f"{base}/api/products/{slug}/prd?v=7")[0] == 404


def test_revise_rejects_empty_requirement(app):
    wait_job(app.jobs.get(app.create_product({"name": "邮件助手", "idea": "整理邮件"})["job"]["id"]))
    with pytest.raises(ValueError, match="不能为空"):
        app.start_revise("邮件助手", {"title": "x", "requirement": "  "})


def test_play_over_http_streams_simulated_steps(server, app):
    _, base = server
    wait_job(app.jobs.get(app.create_product({"name": "玩具剧场", "idea": IDEA})["job"]["id"]))
    url = base + "/api/products/" + urllib.request.quote("玩具剧场")
    status, body, _ = call(url + "/play-intro", {})
    intro = json.loads(body)
    assert status == 200 and intro["scenarios"] and intro["role"] in intro["text"]

    status, body, _ = call(url + "/play", {"messages": [{"role": "assistant", "text": intro["text"]},
                                                        {"role": "user", "text": "你好"}]})
    events = [json.loads(line) for line in body.decode().splitlines()]
    assert status == 200 and events[-1] == {"type": "done"}
    assert any(e["type"] == "data" and e["name"] == "play_feedback" for e in events)


def test_play_without_plan_is_a_plain_400(server, app):
    _, base = server
    from blueprint.workspace import init_workspace
    init_workspace(app.out_root, "空产品", "一句话")
    status, body, _ = call(base + "/api/products/" + urllib.request.quote("空产品") + "/play-intro", {})
    assert status == 400 and "先生成方案" in json.loads(body)["error"]


# ---------------------------------------------------------------------------
# 检查外部项目
# ---------------------------------------------------------------------------

from blueprint.web import audits as audits_mod  # noqa: E402
from blueprint.web.server import check_project_folder  # noqa: E402


def make_project(base, name="minimal-bot"):
    import shutil
    dst = base / "projects" / name
    shutil.copytree(ROOT / "evals/reverse/minimal-bot", dst, ignore=shutil.ignore_patterns("expected.json"))
    return dst


def test_audit_over_http_lists_and_shows_report(server, app, tmp_path):
    (srv, base) = server
    project = make_project(tmp_path)
    status, body, _ = call(f"{base}/api/audits", {"path": str(project)})
    assert status == 201
    data = json.loads(body)
    assert data["slug"] == "audit-minimal-bot"
    wait_job(app.jobs.get(data["job"]["id"]))
    assert app.jobs.get(data["job"]["id"]).status == "done"

    _, body, _ = call(f"{base}/api/audits")
    [item] = json.loads(body)["audits"]
    assert item["name"] == "minimal-bot" and item["root"] == str(project.resolve()) and item["finished"]

    _, body, _ = call(f"{base}/api/audits/audit-minimal-bot")
    detail = json.loads(body)
    assert detail["verdict"] and detail["report"].startswith("# Agent Harness 差距报告")
    assert detail["suggested_prd"] and detail["mode"] == "fast" and detail["job"]["status"] == "done"
    _, body, _ = call(f"{base}/api/products")
    assert json.loads(body)["products"] == []           # 检查结果不会混进产品列表


def test_pick_folder_uses_the_native_picker_and_cancel_is_empty(tmp_path, monkeypatch):
    clear_env(monkeypatch)
    picks = iter(["/Users/x/proj", ""])
    app = App(tmp_path / "out", env_path=tmp_path / ".env", mock=True, folder_picker=lambda: next(picks))
    assert app.pick_folder() == {"path": "/Users/x/proj"}
    assert app.pick_folder() == {"path": ""}


def test_project_folder_rejects_root_home_relative_and_missing(tmp_path):
    for raw, words in [("", "先选择"), ("/", "太大"), (str(Path.home()), "太大"), ("~", "太大"),
                       ("proj", "完整的文件夹路径"), (str(tmp_path / "nope"), "找不到")]:
        with pytest.raises(ValueError, match=words):
            check_project_folder(raw)
    assert check_project_folder(f"'{tmp_path}'") == tmp_path.resolve()      # Finder 拷贝出来的路径可能带引号


def test_same_folder_name_from_another_project_gets_its_own_dir(tmp_path):
    out = tmp_path / "out"
    first, second = make_project(tmp_path / "a"), make_project(tmp_path / "b")
    d = audits_mod.audit_dir_for(out, first)
    d.mkdir(parents=True)
    (d / "inventory.json").write_text(json.dumps({"root": str(first.resolve())}), encoding="utf-8")
    assert audits_mod.audit_dir_for(out, first) == d
    assert audits_mod.audit_dir_for(out, second).name == "audit-minimal-bot-2"


def test_rerun_modes_map_to_run_audit_flags(app, tmp_path, monkeypatch):
    project = make_project(tmp_path)
    slug = app.create_audit({"path": str(project)})["slug"]
    wait_job(app.jobs.latest_for(slug))
    seen = []
    import blueprint.reverse as reverse_mod
    real = reverse_mod.run_audit

    def spy(*args, **kwargs):
        seen.append((kwargs["rejudge"], kwargs["resume"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(reverse_mod, "run_audit", spy)
    for mode in ("recheck", "rejudge", "resume"):
        wait_job(app.rerun_audit(slug, {"mode": mode}))
    assert seen == [(False, False), (True, False), (False, True)]
    with pytest.raises(ValueError, match="不认识"):
        app.rerun_audit(slug, {"mode": "x"})


def test_rerun_when_project_folder_is_gone_is_a_plain_400(server, app, tmp_path):
    import shutil
    (srv, base) = server
    project = make_project(tmp_path)
    slug = app.create_audit({"path": str(project)})["slug"]
    wait_job(app.jobs.latest_for(slug))
    shutil.rmtree(project)
    status, body, _ = call(f"{base}/api/audits/{slug}/run", {"mode": "recheck"})
    assert status == 400 and "找不到了" in json.loads(body)["error"]


def test_resolve_audit_rejects_products_and_traversal(app):
    app.create_product({"name": "玩具剧场", "idea": IDEA})
    for slug in ["玩具剧场", "../out", "audit-..", "audit-x/y", "audit-none"]:
        with pytest.raises(LookupError):
            audits_mod.resolve_audit(app.out_root, slug)


def test_cli_audit_results_show_up_and_unfinished_ones_too(tmp_path):
    out = tmp_path / "out"
    done = out / "audit-cli-proj"
    done.mkdir(parents=True)
    (done / "audit.json").write_text(json.dumps({"root": "/p/cli-proj", "title": "命令行检查的", "completion": 0.5,
                                                 "mode": "agent", "gaps": [{"verdict": "缺失"}, {"verdict": "薄弱"}]}),
                                     encoding="utf-8")
    (done / "差距报告.md").write_text("# 报告\n\n## 一句话判定\n\n**只有雏形。** 必选组件信号覆盖率 **50%**。\n", encoding="utf-8")
    half = out / "audit-half"
    half.mkdir()
    (half / "inventory.json").write_text(json.dumps({"root": "/p/half"}), encoding="utf-8")
    (done / "差距报告.md").write_text("> 对照依据：沿用上次的判断；要重新判断这个项目该有什么，加 `--rejudge`\n\n"
                                    "## 一句话判定\n\n**只有雏形。**\n", encoding="utf-8")
    assert "点右上角「重新判断」" in audits_mod.audit_detail(done)["report"]
    items = {a["slug"]: a for a in audits_mod.list_audits(out)}
    assert items["audit-cli-proj"]["verdict"] == "只有雏形" and items["audit-cli-proj"]["missing"] == 1
    assert items["audit-cli-proj"]["weak"] == 1 and items["audit-cli-proj"]["name"] == "cli-proj"
    assert items["audit-half"]["finished"] is False


def test_one_running_audit_per_project_has_its_own_message():
    jobs = JobManager()
    gate = threading.Event()
    jobs.start("audit", "audit-x", lambda log: gate.wait(5))
    with pytest.raises(ValueError, match="正在检查中"):
        jobs.start("audit", "audit-x", lambda log: None)
    gate.set()
