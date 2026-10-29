"""agent 循环与反向检查 agent 的离线测试：用按剧本返回的假模型，不花钱。"""
import json
import os
from pathlib import Path

import pytest

import blueprint.agent as agent_mod
from blueprint.agent import AgentFailed, Hook, Tool, compact, run_agent
from blueprint.audit_agent import ProjectFiles, make_check
from blueprint.knowledge import FEATURES
from blueprint.llm import Budget
from blueprint.mock import MockRunner
from blueprint.reverse import run_audit
from blueprint.schema import FACT_IDS

ROOT = Path(__file__).resolve().parents[1]
MINIMAL_BOT = ROOT / "evals/reverse/minimal-bot"
SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


def use(name, args, uid=None):
    return {"type": "tool_use", "id": uid or f"tu_{name}_{json.dumps(args, sort_keys=True)}", "name": name, "input": args}


def reply(*blocks, stop="tool_use"):
    return {"content": list(blocks), "stop_reason": stop}


class ScriptRunner:
    """step() 依次返回剧本里的响应；complete() 交给 MockRunner（复核阶段用）。"""

    name = "script"

    def __init__(self, script, max_calls=40):
        self.script = list(script)
        self.budget = Budget(max_calls=max_calls, max_tokens=10_000_000)
        self.seen_tools: list[list[str]] = []
        self.seen_messages: list[list[dict]] = []

    def step(self, stage, system, messages, tools):
        self.budget.check()
        self.budget.record(stage, 10, 10)
        self.seen_tools.append([t["name"] for t in tools])
        self.seen_messages.append(json.loads(json.dumps(messages, default=str)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def complete(self, stage, system, prompt, schema):
        self.budget.record(stage, 10, 10)
        return MockRunner().complete(stage, system, prompt, schema)


def echo_tool(calls):
    def handler(args):
        calls.append(args)
        if args.get("boom"):
            raise RuntimeError("炸了")
        return f"echo:{args.get('text', '')}"
    return Tool("echo", "回显", {"type": "object", "properties": {"text": {"type": "string"}}}, handler)


def quiet(_msg):
    pass


# ---------------------------------------------------------------------------
# 循环本身
# ---------------------------------------------------------------------------

def test_tools_then_finish_returns_result():
    calls = []
    runner = ScriptRunner([reply(use("echo", {"text": "a"})), reply(use("finish", {"answer": "42"}))])
    result = run_agent("t", "sys", "go", [echo_tool(calls)], SCHEMA, runner, log=quiet)
    assert result == {"answer": "42"}
    assert calls == [{"text": "a"}]
    tool_results = runner.seen_messages[1][-1]["content"]
    assert tool_results[0]["content"] == "echo:a"


def test_invalid_finish_is_sent_back_then_accepted():
    runner = ScriptRunner([reply(use("finish", {"answer": 1}, "f1")), reply(use("finish", {"answer": "ok"}, "f2"))])
    assert run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet) == {"answer": "ok"}
    sent_back = runner.seen_messages[1][-1]["content"][0]
    assert sent_back["tool_use_id"] == "f1" and "交卷不合格" in sent_back["content"]


def test_custom_check_rejects_until_fixed():
    runner = ScriptRunner([reply(use("finish", {"answer": "bad"}, "f1")), reply(use("finish", {"answer": "good"}, "f2"))])
    check = lambda r: [] if r["answer"] == "good" else ["answer 必须是 good"]  # noqa: E731
    assert run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet, check=check)["answer"] == "good"


def test_three_bad_finishes_fail():
    runner = ScriptRunner([reply(use("finish", {"answer": i}, f"f{i}")) for i in range(3)])
    with pytest.raises(AgentFailed, match="连续 3 次"):
        run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet)


def test_text_only_reply_is_nudged_once_then_fails():
    text = {"type": "text", "text": "我觉得答案是 42"}
    runner = ScriptRunner([reply(text, stop="end_turn"), reply(text, stop="end_turn")])
    with pytest.raises(AgentFailed, match="没有调用 finish"):
        run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet)
    assert "finish" in runner.seen_messages[1][-1]["content"]


def test_empty_finish_asks_for_text_json_and_accepts_it():
    text = {"type": "text", "text": '交卷：\n```json\n{"answer": "42"}\n```'}
    runner = ScriptRunner([reply(use("finish", {}, "f1")), reply(text, stop="end_turn")])
    assert run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet) == {"answer": "42"}
    assert "文字回复里输出完整的交卷 JSON" in runner.seen_messages[1][-1]["content"][0]["content"]


def test_invalid_text_json_is_sent_back():
    bad = {"type": "text", "text": '{"answer": 1}'}
    good = {"type": "text", "text": '{"answer": "ok"}'}
    runner = ScriptRunner([reply(bad, stop="end_turn"), reply(good, stop="end_turn")])
    assert run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet) == {"answer": "ok"}
    assert "交卷不合格" in runner.seen_messages[1][-1]["content"]


def test_three_empty_finishes_fail():
    runner = ScriptRunner([reply(use("finish", {}, f"f{i}")) for i in range(3)])
    with pytest.raises(AgentFailed, match="参数为空"):
        run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet)


def test_last_turn_offers_only_finish():
    calls = []
    runner = ScriptRunner([reply(use("echo", {"text": "1"})), reply(use("echo", {"text": "2"})),
                           reply(use("finish", {"answer": "done"}))])
    assert run_agent("t", "sys", "go", [echo_tool(calls)], SCHEMA, runner, log=quiet, max_turns=3)["answer"] == "done"
    assert runner.seen_tools[0] == ["echo", "finish"] and runner.seen_tools[2] == ["finish"]


def test_turns_used_up_without_finish_fails():
    runner = ScriptRunner([reply(use("echo", {"text": str(i)})) for i in range(2)])
    with pytest.raises(AgentFailed):
        run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=quiet, max_turns=2)


def test_parallel_calls_each_get_their_own_result():
    calls = []
    runner = ScriptRunner([reply(use("echo", {"text": "x"}, "a"), use("echo", {"text": "y"}, "b"),
                                 use("echo", {"text": "z"}, "c")),
                           reply(use("finish", {"answer": "xyz"}))])
    run_agent("t", "sys", "go", [echo_tool(calls)], SCHEMA, runner, log=quiet)
    results = {r["tool_use_id"]: r["content"] for r in runner.seen_messages[1][-1]["content"]}
    assert results == {"a": "echo:x", "b": "echo:y", "c": "echo:z"}


def test_tool_error_goes_into_result_and_loop_continues():
    runner = ScriptRunner([reply(use("echo", {"boom": True})), reply(use("nope", {})),
                           reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=quiet)
    assert runner.seen_messages[1][-1]["content"][0]["content"] == "错误：炸了"
    assert "没有叫 nope 的工具" in runner.seen_messages[2][-1]["content"][0]["content"]


def test_thinking_blocks_are_kept_in_history(tmp_path):
    thinking = {"type": "thinking", "thinking": "先读文件", "signature": "sig"}
    runner = ScriptRunner([reply(thinking, use("echo", {"text": "a"})), reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=quiet, transcript=tmp_path / "t.jsonl")
    assert runner.seen_messages[1][1]["content"][0] == thinking
    assert len((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_runner_without_step_is_rejected():
    with pytest.raises(AgentFailed):
        run_agent("t", "sys", "go", [], SCHEMA, MockRunner(), log=quiet)


# ---------------------------------------------------------------------------
# 钩子（s04）
# ---------------------------------------------------------------------------

def test_before_tool_hook_blocks_without_running_the_tool():
    calls = []
    hook = Hook(before_tool=lambda name, args: "不许" if args.get("text") == "x" else None)
    runner = ScriptRunner([reply(use("echo", {"text": "x"}, "a"), use("echo", {"text": "y"}, "b")),
                           reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool(calls)], SCHEMA, runner, log=quiet, hooks=[hook])
    assert calls == [{"text": "y"}]
    results = {r["tool_use_id"]: r["content"] for r in runner.seen_messages[1][-1]["content"]}
    assert results == {"a": "不许", "b": "echo:y"}


def test_after_tool_hook_rewrites_result():
    hook = Hook(after_tool=lambda name, args, content: content.upper())
    runner = ScriptRunner([reply(use("echo", {"text": "a"})), reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=quiet, hooks=[hook])
    assert runner.seen_messages[1][-1]["content"][0]["content"] == "ECHO:A"


def test_before_finish_hook_rejects_until_fixed():
    hook = Hook(before_finish=lambda r: [] if r["answer"] == "42" else ["答案不对"])
    runner = ScriptRunner([reply(use("finish", {"answer": "41"})), reply(use("finish", {"answer": "42"}))])
    assert run_agent("t", "sys", "go", [], SCHEMA, runner, log=quiet, hooks=[hook]) == {"answer": "42"}
    assert "答案不对" in runner.seen_messages[1][-1]["content"][0]["content"]


def test_describe_logs_even_blocked_calls():
    lines = []
    hook = Hook(before_tool=lambda name, args: "不许")
    runner = ScriptRunner([reply(use("echo", {"text": "a"})), reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=lines.append, hooks=[hook],
              describe=lambda name, args: f"回显 {args['text']}")
    assert "    · 回显 a" in lines


def test_repeat_guard_blocks_third_identical_call():
    calls = []
    runner = ScriptRunner([reply(use("echo", {"text": "a"}, "1")), reply(use("echo", {"text": "a"}, "2")),
                           reply(use("echo", {"text": "a"}, "3")), reply(use("echo", {"text": "b"}, "4")),
                           reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool(calls)], SCHEMA, runner, log=quiet)
    assert calls == [{"text": "a"}, {"text": "a"}, {"text": "b"}]
    assert "完全一样" in runner.seen_messages[3][-1]["content"][0]["content"]


# ---------------------------------------------------------------------------
# 收起旧的工具结果（s08）
# ---------------------------------------------------------------------------

def _history(rounds, size):
    messages = [{"role": "user", "content": "go"}]
    for i in range(rounds):
        messages.append({"role": "assistant", "content": [
            {"type": "thinking", "thinking": f"想{i}", "signature": "s"},
            {"type": "tool_use", "id": f"u{i}", "name": "read_file", "input": {"path": f"f{i}.py"}}]})
        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"u{i}", "content": "x" * size}]})
    return messages


def test_compact_does_nothing_under_limit():
    messages = _history(4, 100)
    before = json.dumps(messages)
    assert compact(messages, lambda n, a: n, limit=1000) == (0, 0)
    assert json.dumps(messages) == before


def test_compact_collapses_all_but_recent_rounds_and_keeps_pairs():
    messages = _history(5, 1000)
    assistants = json.dumps([m for m in messages if m["role"] == "assistant"])
    collapsed, freed = compact(messages, lambda n, a: f"{n} {a['path']}", limit=3000, keep=2)
    assert collapsed == 3 and freed > 2500
    results = [m["content"][0] for m in messages if m["role"] == "user" and isinstance(m["content"], list)]
    assert [r["tool_use_id"] for r in results] == ["u0", "u1", "u2", "u3", "u4"]
    assert results[0]["content"] == "（已收起：read_file f0.py，原 1,000 字；需要时重新调用）"
    assert results[3]["content"] == results[4]["content"] == "x" * 1000
    assert json.dumps([m for m in messages if m["role"] == "assistant"]) == assistants
    assert compact(messages, lambda n, a: n, limit=3000, keep=2) == (0, 0)   # 已收起的不再重复收


def test_loop_compacts_when_history_grows(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_mod, "COMPACT_AT", 300)
    lines = []
    runner = ScriptRunner([reply(use("echo", {"text": "a" * 200}, "1")), reply(use("echo", {"text": "b" * 200}, "2")),
                           reply(use("echo", {"text": "c" * 200}, "3")), reply(use("finish", {"answer": "ok"}))])
    run_agent("t", "sys", "go", [echo_tool([])], SCHEMA, runner, log=lines.append, transcript=tmp_path / "t.jsonl")
    sent = runner.seen_messages[3]
    assert sent[2]["content"][0]["content"].startswith("（已收起：echo")
    assert sent[-1]["content"][0]["content"] == "echo:" + "c" * 200
    assert any("收起早先的 1 条" in line for line in lines)
    assert '"compacted": 1' in (tmp_path / "t.jsonl").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 只读文件工具的安全边界
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
    (root / ".env.example").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    (root / "config.pem").write_text("-----BEGIN-----\n", encoding="utf-8")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("x", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside secret", encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", root / "link.txt")
    return root


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "link.txt", ".env", "config.pem",
                                  "node_modules/x/i.js", "src/../../outside.txt"])
def test_read_file_refuses_paths_outside_or_secret(project, path):
    with pytest.raises(ValueError, match="拒绝|不存在"):
        ProjectFiles(project).read_file({"path": path})


def test_read_file_returns_numbered_lines_and_records_seen(project):
    files = ProjectFiles(project)
    out = files.read_file({"path": "./src/app.py", "start_line": 2})
    assert "    2  line2" in out and "line1" not in out
    assert files.seen == {"src/app.py": 3}
    assert "ANTHROPIC_API_KEY" in files.read_file({"path": ".env.example"})


def test_search_skips_secrets_and_symlinks(project):
    out = ProjectFiles(project).search({"pattern": "secret|line2"})
    assert "src/app.py:2" in out
    assert "sk-secret" not in out and "outside" not in out


def test_list_dir_hides_ignored_dirs(project):
    out = ProjectFiles(project).list_dir({})
    assert "src/" in out and "node_modules" not in out and ".env\n" not in out + "\n"


def _result(evidence):
    return {"intent": {}, "components": {"s01": {"strength": "strong", "evidence": evidence}}}


def test_evidence_must_come_from_files_actually_read(project):
    files = ProjectFiles(project)
    check = make_check(files, lambda _r: ["s01"])
    ev = [{"file": "src/app.py", "line": 2, "note": "主循环"}]
    assert any("没有读过" in e for e in check(_result(ev)))
    files.read_file({"path": "src/app.py"})
    assert check(_result(ev)) == []
    assert any("第 9 行不存在" in e for e in check(_result([{**ev[0], "line": 9}])))
    assert any("至少要有一条代码证据" in e for e in check(_result([])))


def test_required_components_must_be_judged(project):
    errors = make_check(ProjectFiles(project), lambda _r: ["s01", "s03"])(_result([]))
    assert any("s03" in e and "必须给出结论" in e for e in errors)


# ---------------------------------------------------------------------------
# 接进 run_audit
# ---------------------------------------------------------------------------

def _intent():
    return {"title": "minimal-bot", "one_liner": "运维命令行助手", "product_summary": "调用 shell 的助手",
            "facts": {k: {"value": "x", "status": "待确认"} for k in FACT_IDS},
            "features": {f.id: {"value": "no", "evidence": ""} for f in FEATURES}, "unknowns": []}


def _flagged(project=MINIMAL_BOT):
    from blueprint.scanner import scan_project
    return [cid for cid, sig in scan_project(project).components.items() if sig.strength != "none"]


def _audit_script(skip=()):
    finding = {"strength": "strong", "evidence": [{"file": "src/bot.py", "line": 16, "note": "while True 循环调用模型"}]}
    tools = {"strength": "weak", "evidence": [{"file": "src/bot.py", "line": 7, "note": "只有一个 bash 工具"}]}
    components = {cid: {"strength": "none", "evidence": []} for cid in _flagged() if cid not in skip}
    components.update({"s01": finding, "s02": tools})
    return [reply(use("list_dir", {"path": "."}), use("read_file", {"path": "src/bot.py"})),
            reply(use("finish", {"intent": _intent(), "components": components}))]


def test_run_audit_uses_agent_findings(tmp_path):
    runner = ScriptRunner(_audit_script())
    audit, doc = run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=quiet)
    assert audit.mode == "agent" and audit.agent_stats == {"files_seen": 1}
    gaps = {g.id: g for g in audit.gaps}
    assert gaps["s02"].present == "weak"
    assert gaps["s01"].evidence == ["src/bot.py:16 while True 循环调用模型"]
    report = doc.read_text(encoding="utf-8")
    assert "agent 阅读项目代码" in report and "快速扫描模式" not in report
    assert (tmp_path / "out/stages/audit_agent.transcript.jsonl").exists()


def test_scanner_hits_must_be_rechecked_and_unjudged_count_as_none(tmp_path):
    keyword_only = ROOT / "evals/reverse/keyword-only"
    flagged = _flagged(keyword_only)
    assert {"s03", "s09"} <= set(flagged)          # 扫描器被注释和变量名骗了
    loop = {"strength": "strong", "evidence": [{"file": "src/agent.py", "line": 42, "note": "while True 调模型"}]}

    def finish(skip):
        components = {cid: {"strength": "none", "evidence": []} for cid in flagged if cid != skip}
        components["s01"] = loop
        return reply(use("finish", {"intent": _intent(), "components": components}, f"f-{skip}"))

    runner = ScriptRunner([reply(use("read_file", {"path": "src/agent.py"})), finish("s09"), finish("")])
    audit, _ = run_audit(keyword_only, runner, tmp_path / "out", log=quiet)
    rejected = runner.seen_messages[2][-1]["content"][0]["content"]
    assert "s09" in rejected and "扫描器判为有" in rejected
    present = {g.id: g.present for g in audit.gaps}
    assert present["s03"] == "none" and present["s09"] == "none"
    assert all(present[cid] == "none" for cid in present if cid not in flagged)


def test_resume_reuses_agent_findings(tmp_path):
    run_audit(MINIMAL_BOT, ScriptRunner(_audit_script()), tmp_path / "out", log=quiet)
    again = ScriptRunner([])
    audit, _ = run_audit(MINIMAL_BOT, again, tmp_path / "out", log=quiet, resume=True)
    assert audit.mode == "agent" and again.seen_tools == []
    assert {g.id: g.present for g in audit.gaps}["s02"] == "weak"


def test_run_audit_falls_back_to_scan_when_agent_errors(tmp_path):
    runner = ScriptRunner([RuntimeError("400 tools not supported")])
    audit, doc = run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=quiet)
    assert audit.mode == "fast" and "agent 未完成" in audit.mode_note
    assert "⚠️ 本次是快速扫描模式" in doc.read_text(encoding="utf-8")


def test_run_audit_fast_flag_skips_agent(tmp_path):
    runner = ScriptRunner([])
    audit, _ = run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=quiet, fast=True)
    assert audit.mode == "fast" and "--fast" in audit.mode_note and runner.seen_tools == []


def test_run_audit_skips_agent_when_budget_too_small(tmp_path):
    runner = ScriptRunner([], max_calls=5)
    audit, _ = run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=quiet)
    assert audit.mode == "fast" and "调用次数太少" in audit.mode_note


def test_mock_runner_report_has_no_fallback_warning(tmp_path):
    audit, doc = run_audit(MINIMAL_BOT, MockRunner(), tmp_path / "out", log=quiet)
    assert audit.mode == "fast" and audit.mode_note == ""
    assert "快速扫描模式" not in doc.read_text(encoding="utf-8")


def test_cli_budget_defaults_depend_on_command(monkeypatch):
    from blueprint.cli import build_parser, make_runner
    if not os.getenv("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-cli")
    audit = make_runner(build_parser().parse_args(["audit", "x"]))
    fast = make_runner(build_parser().parse_args(["audit", "x", "--fast"]))
    plan = make_runner(build_parser().parse_args(["plan", "x"]))
    assert (audit.budget.max_calls, fast.budget.max_calls, plan.budget.max_calls) == (40, 16, 40)
    assert make_runner(build_parser().parse_args(["verify", "x", "--max-calls", "9"])).budget.max_calls == 9
