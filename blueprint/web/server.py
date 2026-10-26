"""本地网页服务：只监听本机，给不会用终端的用户一个浏览器界面。

服务端只用标准库。页面源码在仓库根目录的 web/（React + assistant-ui），
构建产物提交在 static/ 里，所以使用者不需要装 Node。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from blueprint import chat, providers
from blueprint.web.jobs import JobManager, friendly_error
from blueprint.web.views import list_products, product_detail, resolve_workspace

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000


class App:
    """一个界面实例的全部状态；测试里换掉 out_root / env_path 即可隔离。"""

    def __init__(self, out_root: Path, env_path: Path = providers.ENV_PATH, mock: bool = False):
        self.out_root = Path(out_root)
        self.env_path = Path(env_path)
        self.mock = mock
        self.jobs = JobManager()

    # -- 模型配置 ------------------------------------------------------------

    def configured(self) -> bool:
        if self.mock:
            return True
        return providers.is_real_key(read_key(self.env_path) or os.environ.get("ANTHROPIC_API_KEY", ""))

    def settings(self) -> dict:
        env = providers.read_env(self.env_path)
        key = env.get("ANTHROPIC_API_KEY", "")
        base = env.get("ANTHROPIC_BASE_URL") or None
        current = next((p["key"] for p in providers.PROVIDERS.values() if p["base"] == base), "")
        return {
            "mock": self.mock,
            "configured": self.configured(),
            "provider": current if providers.is_real_key(key) else "",
            "model": env.get("MODEL_ID", ""),
            "key_masked": mask(key) if providers.is_real_key(key) else "",
            "providers": [{k: p[k] for k in ("key", "name", "model", "key_page")}
                          for p in providers.PROVIDERS.values()],
        }

    def save_settings(self, body: dict) -> dict:
        provider = providers.PROVIDER_BY_KEY.get(body.get("provider", ""))
        if not provider:
            raise ValueError("请选择模型服务商")
        api_key = (body.get("api_key") or "").strip() or read_key(self.env_path)
        if not providers.is_real_key(api_key):
            raise ValueError("请粘贴 API Key")
        model = (body.get("model") or "").strip() or provider["model"]
        ok, message = providers.test_connection(provider["base"], api_key, model)
        if not ok:
            return {"ok": False, "message": message}
        providers.write_env(api_key, model, provider["base"], path=self.env_path)
        providers.apply_to_process(api_key, model, provider["base"])
        return {"ok": True, "message": message}

    # -- 产品 ----------------------------------------------------------------

    def make_runner(self):
        if self.mock:
            from blueprint.mock import MockRunner
            return MockRunner()
        from blueprint.llm import AnthropicRunner, Budget
        return AnthropicRunner(budget=Budget())

    def product(self, slug: str) -> dict:
        ws = resolve_workspace(self.out_root, slug)
        job = self.jobs.latest_for(slug)
        detail = product_detail(ws)
        questions = detail["plan"]["unknowns"] if detail["plan"] else []
        key = sum(1 for q in detail["plan"]["questions"] if q.get("priority") == 1) if detail["plan"] else 0
        return {**detail, "job": job.to_dict() if job else None,
                "answer_intro": chat.answer_intro(questions, key) if questions else ""}

    # -- 对话 ----------------------------------------------------------------

    def chat_model(self):
        if not self.configured():
            raise ValueError("还没配置模型，先到「模型设置」填好 API Key。")
        return chat.MockChat() if self.mock else chat.AnthropicChat()

    def intake_chat(self, body: dict):
        model = self.chat_model()
        return chat.intake_events(chat.parse_messages(body.get("messages")), model)

    def answer_chat(self, slug: str, body: dict):
        ws = resolve_workspace(self.out_root, slug)
        plan = product_detail(ws)["plan"]
        if not plan:
            raise ValueError("还没有方案，先生成方案再回答问题。")
        model = self.chat_model()
        return chat.answer_events(plan["unknowns"], chat.parse_messages(body.get("messages")),
                                  (ws / "PRD.md").read_text(encoding="utf-8"), model)

    def save_answers(self, slug: str, body: dict) -> dict:
        from blueprint.workspace import record_answers
        ws = resolve_workspace(self.out_root, slug)
        items = body.get("answers")
        if not isinstance(items, list):
            raise ValueError("回答格式不对")
        # 界面上问的是大白话版本；写进 PRD 时带上原问题，下一轮推导能对上是哪一条
        plan = product_detail(ws)["plan"]
        originals = {q["text"]: "；".join([q["original"], *q.get("merged", [])]) for q in plan["questions"]} if plan else {}
        pairs = []
        for i in items:
            if not isinstance(i, dict):
                continue
            q = str(i.get("question") or "")
            original = originals.get(q, q)
            pairs.append((q if original == q else f"{q}（原问题：{original}）", str(i.get("answer") or "")))
        if not self.configured():
            raise ValueError("还没配置模型，先到「模型设置」填好 API Key。")
        record_answers(ws, pairs)
        return {"job": self.start_plan(slug).to_dict()}

    def create_product(self, body: dict) -> dict:
        if not self.configured():
            raise ValueError("还没配置模型，先到「模型设置」填好 API Key。")
        from blueprint.workspace import PRD_NAME, init_workspace, slugify
        name = (body.get("name") or "").strip()
        if name and (self.out_root / slugify(name) / PRD_NAME).exists():
            raise ValueError(f"已经有一个叫「{name}」的产品了，换个名字吧。")
        ws = init_workspace(self.out_root, name, body.get("idea") or "")
        job = self.start_plan(ws.name)
        return {"slug": ws.name, "job": job.to_dict()}

    def start_plan(self, slug: str):
        """（重新）推导方案。总是带断点续跑：输入没变的阶段直接沿用，不重复计费。"""
        ws = resolve_workspace(self.out_root, slug)
        if not self.configured():
            raise ValueError("还没配置模型，先到「模型设置」填好 API Key。")

        def task(log):
            from blueprint.forward import run_plan
            from blueprint.workspace import log_plan
            runner = self.make_runner()
            plan, doc = run_plan((ws / "PRD.md").read_text(encoding="utf-8"), runner, ws,
                                 resume=True, log=log)
            log_plan(ws, plan, doc)
            rewrite_plain(ws, runner, log)
            fill_prd_sections(ws, runner, log)
            log("✓ 方案已生成")

        return self.jobs.start("plan", slug, task)

    # -- 加新需求与版本历史 ----------------------------------------------------

    def revise_chat(self, slug: str, body: dict):
        ws = resolve_workspace(self.out_root, slug)
        model = self.chat_model()
        return chat.revise_events(chat.parse_messages(body.get("messages")),
                                  (ws / "PRD.md").read_text(encoding="utf-8"), model)

    def start_revise(self, slug: str, body: dict):
        """PRD 升一版、把新需求追加进去、重推方案（没变的阶段沿用缓存）。返回选型变化给页面。"""
        ws = resolve_workspace(self.out_root, slug)
        if not self.configured():
            raise ValueError("还没配置模型，先到「模型设置」填好 API Key。")
        title = (body.get("title") or "").strip()
        requirement = (body.get("requirement") or "").strip()
        if not requirement:
            raise ValueError("新需求不能为空")
        # 第一行会写进版本记录，所以把一句话标题放最前面
        text = f"{title}\n\n{requirement}" if title else requirement

        def task(log):
            from blueprint.knowledge import COMPONENT_BY_ID
            from blueprint.workspace import revise_workspace
            runner = self.make_runner()
            result = revise_workspace(ws, text, runner, log=log, warn_undigested=False, source="网页界面·加新需求")
            rewrite_plain(ws, runner, log)
            fill_prd_sections(ws, runner, log)
            log(f"✓ 已升到 V{result['new_version']}，方案已重新推导")
            return {"old_version": result["old_version"], "new_version": result["new_version"],
                    "diff": [{"id": cid, "name": COMPONENT_BY_ID[cid].name if cid in COMPONENT_BY_ID else cid,
                              "before": before, "after": after} for cid, before, after in result["diff"]]}

        return self.jobs.start("revise", slug, task)

    def history(self, slug: str) -> dict:
        from blueprint.workspace import current_version, log_entries, version_table
        ws = resolve_workspace(self.out_root, slug)
        prd = (ws / "PRD.md").read_text(encoding="utf-8")
        snapshots = sorted(int(p.stem[1:]) for p in (ws / "prd").glob("V*.md") if p.stem[1:].isdigit())
        return {"current": current_version(prd), "versions": version_table(prd),
                "log": log_entries(ws), "snapshots": snapshots}

    def prd_text(self, slug: str, version: int | None) -> dict:
        from blueprint.workspace import current_version
        ws = resolve_workspace(self.out_root, slug)
        prd = (ws / "PRD.md").read_text(encoding="utf-8")
        current = current_version(prd)
        if version is None or version == current:
            return {"version": current, "text": prd, "current": True}
        snapshot = ws / "prd" / f"V{version}.md"
        if not snapshot.is_file():
            raise LookupError(f"没有 V{version} 的需求文档")
        return {"version": version, "text": snapshot.read_text(encoding="utf-8"), "current": False}

    def handoff(self, slug: str) -> tuple[str, bytes]:
        from blueprint.handoff import build_handoff, handoff_filename
        ws = resolve_workspace(self.out_root, slug)
        return handoff_filename(ws), build_handoff(ws)

    def reveal(self, slug: str) -> None:
        ws = resolve_workspace(self.out_root, slug)
        if sys.platform == "darwin":
            subprocess.run(["open", str(ws)], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(ws)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(ws)], check=False)


def rewrite_plain(ws: Path, runner, log) -> None:
    """推导后把待确认问题改成大白话并分流。只是锦上添花：失败就用原问题，不影响方案。"""
    try:
        from blueprint.plain import rewrite_questions
        rewrite_questions(json.loads((ws / "plan.json").read_text(encoding="utf-8")), runner, ws, log=log)
    except Exception as exc:  # noqa: BLE001
        log(f"  ⚠ 问题改写没成功，先显示原问题：{friendly_error(exc)}")


def fill_prd_sections(ws: Path, runner, log) -> None:
    """把 PRD 第 2–5 节整理出来（只动模板和之前自动整理过的小节）。失败不影响方案。"""
    try:
        from blueprint.prd_fill import fill_prd
        fill_prd(ws, json.loads((ws / "plan.json").read_text(encoding="utf-8")), runner, log=log)
    except Exception as exc:  # noqa: BLE001
        log(f"  ⚠ 需求文档没整理成功，不影响方案：{friendly_error(exc)}")


def read_key(env_path: Path) -> str:
    return providers.read_env(env_path).get("ANTHROPIC_API_KEY", "")


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "已填写"


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentBlueprint"

        def log_message(self, fmt, *args):  # 页面轮询很频繁，不刷屏
            pass

        # -- 安全：只认本机地址，挡住其他网站借浏览器对本机服务发请求 ----------------

        def _allowed_hosts(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in self._allowed_hosts()

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            return urlparse(origin).netloc in self._allowed_hosts()

        # -- 响应 -------------------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("提交的内容太长了")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("请求格式不对")
            return data

        def _stream(self, events) -> None:
            """逐行推送 JSON 事件（NDJSON）。HTTP/1.0 下写完关连接，浏览器就知道结束了。"""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True

            def emit(event: dict) -> None:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()

            try:
                try:
                    for event in events:
                        emit(event)
                except (BrokenPipeError, ConnectionResetError):
                    raise
                except Exception as exc:  # noqa: BLE001 —— 响应头已发出，错误只能作为事件推给页面
                    emit({"type": "error", "message": friendly_error(exc)})
                emit({"type": "done"})
            except (BrokenPipeError, ConnectionResetError):
                pass                                  # 用户点了停止或关了页面

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "/index.html") else path.removeprefix("/static/")
            file = (STATIC / name).resolve()
            if not file.is_relative_to(STATIC) or not file.is_file():
                return self._error(404, "页面不存在")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, file.read_bytes(), ctype)

        # -- 路由 -------------------------------------------------------------

        def do_GET(self):
            if not self._host_ok():
                return self._error(403, "只允许从本机访问")
            url = urlparse(self.path)
            path = url.path
            try:
                if path == "/api/settings":
                    return self._json(app.settings())
                if path == "/api/products":
                    return self._json({"products": list_products(app.out_root)})
                m = re.fullmatch(r"/api/products/([^/]+)", path)
                if m:
                    return self._json(app.product(unquote(m.group(1))))
                m = re.fullmatch(r"/api/products/([^/]+)/history", path)
                if m:
                    return self._json(app.history(unquote(m.group(1))))
                m = re.fullmatch(r"/api/products/([^/]+)/prd", path)
                if m:
                    v = parse_qs(url.query).get("v", [""])[0]
                    return self._json(app.prd_text(unquote(m.group(1)), int(v) if v.isdigit() else None))
                m = re.fullmatch(r"/api/products/([^/]+)/handoff", path)
                if m:
                    name, data = app.handoff(unquote(m.group(1)))
                    # 中文文件名按 RFC 6266 用 filename* 传；filename 给不认识 filename* 的老浏览器兜底
                    disposition = f"attachment; filename=\"handoff.zip\"; filename*=UTF-8''{quote(name)}"
                    return self._send(200, data, "application/zip", {"Content-Disposition": disposition})
                m = re.fullmatch(r"/api/jobs/([^/]+)", path)
                if m:
                    job = app.jobs.get(m.group(1))
                    if not job:
                        return self._error(404, "任务不存在（界面重启过的话，刷新页面即可）")
                    since = int(parse_qs(url.query).get("since", ["0"])[0] or 0)
                    return self._json(job.to_dict(since))
                if path.startswith("/api/"):
                    return self._error(404, "接口不存在")
                return self._static(path)
            except LookupError as exc:
                return self._error(404, str(exc))
            except ValueError as exc:
                return self._error(400, str(exc))

        def do_POST(self):
            if not self._host_ok() or not self._origin_ok():
                return self._error(403, "只允许从本机访问")
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._error(415, "请求格式不对")
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/settings":
                    return self._json(app.save_settings(body))
                if path == "/api/products":
                    return self._json(app.create_product(body), 201)
                if path == "/api/chat/intake":
                    return self._stream(app.intake_chat(body))
                m = re.fullmatch(r"/api/products/([^/]+)/(plan|reveal|chat|answers|revise-chat|revise)", path)
                if m:
                    slug, action = unquote(m.group(1)), m.group(2)
                    if action == "revise-chat":
                        return self._stream(app.revise_chat(slug, body))
                    if action == "revise":
                        return self._json({"job": app.start_revise(slug, body).to_dict()})
                    if action == "plan":
                        return self._json({"job": app.start_plan(slug).to_dict()})
                    if action == "chat":
                        return self._stream(app.answer_chat(slug, body))
                    if action == "answers":
                        return self._json(app.save_answers(slug, body))
                    app.reveal(slug)
                    return self._json({"ok": True})
                return self._error(404, "接口不存在")
            except LookupError as exc:
                return self._error(404, str(exc))
            except (ValueError, json.JSONDecodeError) as exc:
                return self._error(400, str(exc))

    return Handler


def create_server(app: App, port: int = 8765) -> ThreadingHTTPServer:
    """端口被占用（比如重复双击）就往后找一个空闲的。"""
    handler = make_handler(app)
    last_error: OSError | None = None
    for candidate in ([port + i for i in range(20)] if port else [0]):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last_error = exc
    raise OSError(f"找不到可用端口：{last_error}")


def serve(out_root: Path, port: int = 8765, mock: bool = False, open_browser: bool = True) -> None:
    app = App(out_root, mock=mock)
    server = create_server(app, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"✅ 界面已启动：{url}")
    print("   浏览器没自动打开的话，把上面的地址复制到浏览器里。")
    print("   用完关掉这个窗口即可（或按 Ctrl+C）。")
    if mock:
        print("   ⚠️ 离线演示模式：不调用模型，结果只按关键词占位，不能用于决策。")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭界面。")
    finally:
        server.server_close()
