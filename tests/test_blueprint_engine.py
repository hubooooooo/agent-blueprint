"""blueprint 引擎的单元测试：全部离线，不需要 API key。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blueprint import evals as ev                      # noqa: E402
from blueprint.forward import run_plan                 # noqa: E402
from blueprint.knowledge import COMPONENTS, FEATURES   # noqa: E402
from blueprint.llm import AnthropicRunner, Budget, BudgetExceeded, StageOutputInvalid, extract_json  # noqa: E402
from blueprint.mock import MockRunner                  # noqa: E402
from blueprint.reverse import run_audit                # noqa: E402
from blueprint.rules import select_components          # noqa: E402
from blueprint.scanner import scan_project             # noqa: E402
from blueprint.schema import EXTRACT_SCHEMA, validate  # noqa: E402


# ---------------------------------------------------------------- 知识层
def test_knowledge_is_consistent():
    assert len(COMPONENTS) == 17
    ids = [c.id for c in COMPONENTS]
    assert ids == [f"s{i:02d}" for i in range(1, 18)]
    for c in COMPONENTS:
        assert (ROOT / c.readme).exists(), c.readme
    targets = {f.component for f in FEATURES}
    assert targets == set(ids) - {"s01", "s02", "s15"}


# ---------------------------------------------------------------- schema
def test_validate_reports_missing_and_enum():
    data = {"title": "x", "one_liner": "", "facts": {}, "features": {"a": {"value": "maybe"}}, "unknowns": []}
    errors = validate(EXTRACT_SCHEMA, data)
    assert any("缺少必填字段 goal" in e for e in errors)
    assert any("maybe" in e for e in errors)


def test_extract_json_tolerates_fence_and_prose():
    assert extract_json('前言 ```json\n{"a": 1}\n``` 后记') == {"a": 1}
    assert extract_json('说明：{"a": {"b": "}"}} 结束') == {"a": {"b": "}"}}
    with pytest.raises(StageOutputInvalid):
        extract_json("没有 json")


# ---------------------------------------------------------------- 规则
def _features(**kw):
    return {k: {"value": v, "evidence": ""} for k, v in kw.items()}


def test_rules_always_select_loop_and_tools():
    got = {d.id: d.decision for d in select_components({})}
    assert got["s01"] == "必选" and got["s02"] == "必选"
    assert all(v == "待确认" for k, v in got.items() if k not in ("s01", "s02", "s15"))
    assert got["s15"] == "放弃"


def test_rules_s15_thresholds():
    got = {d.id: d.decision for d in select_components(_features(destructive_ops="yes", audit_needed="yes", large_knowledge="yes"))}
    assert got["s15"] == "必选"
    got = {d.id: d.decision for d in select_components(_features(destructive_ops="yes", audit_needed="later", large_knowledge="later"))}
    assert got["s15"] == "二期"


def test_rules_match_every_eval_case():
    for case in ev.forward_cases():
        assert ev.check_rules(case) == [], case.name


# ---------------------------------------------------------------- 扫描器
def test_scanner_minimal_bot():
    inv = scan_project(ROOT / "evals/reverse/minimal-bot")
    assert "anthropic" in inv.llm_sdks
    assert inv.components["s01"].strength != "none"
    assert inv.components["s03"].strength == "none"
    assert inv.components["s12"].strength == "none"
    assert inv.acceptance["testable"]["status"] == "fail"
    assert inv.entry_points == ["src/bot.py"]


def test_scanner_skips_excluded_dirs(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.py").write_text("cron schedule MEMORY.md", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')", encoding="utf-8")
    inv = scan_project(tmp_path)
    assert inv.file_count == 1
    assert inv.components["s12"].strength == "none"


# ---------------------------------------------------------------- 正向
def test_forward_plan_offline(tmp_path: Path):
    text = (ROOT / "evals/forward/toy-theater/input.md").read_text(encoding="utf-8")
    runner = MockRunner()
    plan, doc = run_plan(text, runner, tmp_path / "out", log=lambda _m: None)
    assert doc.exists() and (tmp_path / "out" / "plan.json").exists()
    assert runner.calls == ["extract", "model", "design", "review"]
    content = doc.read_text(encoding="utf-8")
    for section in ev.PLAN_SECTIONS:
        assert section in content, section
    assert "```mermaid" in content
    assert len(plan.components) == 17


def test_forward_resume_skips_finished_stages(tmp_path: Path):
    text = "做一个定时每天发日报的机器人"
    run_plan(text, MockRunner(), tmp_path / "out", log=lambda _m: None)
    runner = MockRunner()
    run_plan(text, runner, tmp_path / "out", resume=True, log=lambda _m: None)
    assert runner.calls == []


def test_forward_retries_design_when_review_fails(tmp_path: Path):
    class Strict(MockRunner):
        def complete(self, stage, system, prompt, schema):
            data = super().complete(stage, system, prompt, schema)
            if stage == "review":
                return {"ok": False, "issues": [{"section": "工具清单", "problem": "太少", "severity": "high"}], "summary": "不过"}
            return data
    runner = Strict()
    plan, _ = run_plan("一个点子", runner, tmp_path / "out", log=lambda _m: None)
    assert runner.calls == ["extract", "model", "design", "review", "design_retry", "review_retry"]
    assert plan.design_attempts == 2


# ---------------------------------------------------------------- 反向
def test_reverse_audit_offline(tmp_path: Path):
    audit, doc = run_audit(ROOT / "evals/reverse/minimal-bot", MockRunner(), tmp_path / "out", log=lambda _m: None)
    content = doc.read_text(encoding="utf-8")
    for section in ev.AUDIT_SECTIONS:
        assert section in content, section
    assert (tmp_path / "out" / "本该有的PRD.md").exists()
    by_id = {g.id: g for g in audit.gaps}
    # README 提到删除文件与重启服务 → mock 判 destructive_ops=yes → s03 必选且缺失 → P0
    assert by_id["s03"].expected == "必选" and by_id["s03"].present == "none" and by_id["s03"].priority == "P0"
    assert by_id["s01"].verdict == "已具备"
    assert 0.0 <= audit.completion <= 1.0


def test_reverse_audit_with_prd_overrides_features(tmp_path: Path):
    prd = "每天定时跑一遍。会记住用户偏好。"
    audit, _ = run_audit(ROOT / "evals/reverse/minimal-bot", MockRunner(), tmp_path / "out",
                         prd_text=prd, log=lambda _m: None)
    by_id = {g.id: g for g in audit.gaps}
    assert by_id["s12"].expected == "必选" and by_id["s12"].priority == "P0"
    assert by_id["s09"].expected == "必选"


def test_reverse_rejects_missing_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        run_audit(tmp_path / "nope", MockRunner(), tmp_path / "out", log=lambda _m: None)


# ---------------------------------------------------------------- 真实 runner 的护栏（用假 client）
class _FakeClient:
    def __init__(self, texts):
        self._texts = list(texts)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        text = self._texts.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                               stop_reason="end_turn")


def _extract_ok():
    facts = {k: {"value": "x", "status": "明确", "source": ""} for k in
             ["goal", "users", "core_loop", "deliverable", "boundaries", "constraints"]}
    return json.dumps({"title": "t", "one_liner": "o", "facts": facts, "features": {}, "unknowns": []})


def test_anthropic_runner_retries_once_on_bad_json(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    runner = AnthropicRunner(client=_FakeClient(["不是 json", _extract_ok()]), budget=Budget(max_calls=5))
    data = runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)
    assert data["title"] == "t"
    assert runner.budget.calls == 2


def test_anthropic_runner_gives_up_after_two_bad_outputs(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    runner = AnthropicRunner(client=_FakeClient(["x", "{}"]), budget=Budget(max_calls=5))
    with pytest.raises(StageOutputInvalid):
        runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)


def test_budget_stops_before_call(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    runner = AnthropicRunner(client=_FakeClient([_extract_ok()]), budget=Budget(max_calls=0))
    with pytest.raises(BudgetExceeded):
        runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)


# ---------------------------------------------------------------- CLI
def test_cli_plan_and_audit_mock(tmp_path: Path):
    idea = tmp_path / "idea.md"
    idea.write_text("做一个每天定时提醒喝水的机器人", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "blueprint", "plan", str(idea), "--mock", "-o", str(tmp_path / "p")],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "p" / "方案.md").exists()
    r = subprocess.run([sys.executable, "-m", "blueprint", "audit", str(ROOT / "evals/reverse/minimal-bot"),
                        "--mock", "-o", str(tmp_path / "a")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "a" / "差距报告.md").exists()
