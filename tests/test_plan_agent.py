"""方案推导 agent 的离线测试：设计自检规则、接进 run_plan、审稿打回重写、退回固定流程、续跑。"""
import copy
import json
from pathlib import Path

import pytest

from blueprint.forward import run_plan
from blueprint.llm import Budget
from blueprint.mock import MockRunner
from blueprint.plan_agent import check_design

ROOT = Path(__file__).resolve().parents[1]
IDEA = (ROOT / "evals/forward/toy-theater/input.md").read_text(encoding="utf-8")
MOCK = MockRunner()
ELEMENTS = MOCK.complete("model", "", "", {})
DESIGN = MOCK.complete("design", "", "", {})
EXTRACT_DESTRUCTIVE = {"features": {"destructive_ops": {"value": "yes"}}}


def quiet(_m):
    pass


def use(name, args, uid):
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


def reply(*blocks):
    return {"content": list(blocks), "stop_reason": "tool_use"}


class ScriptRunner:
    """step() 按剧本；complete() 交给 MockRunner，审稿结果可以按次指定。"""

    name = "script"

    def __init__(self, script, reviews=(), max_calls=40):
        self.script = list(script)
        self.reviews = list(reviews)
        self.budget = Budget(max_calls=max_calls, max_tokens=10_000_000)
        self.prompts: list[str] = []
        self.seen: list[list[dict]] = []

    def step(self, stage, system, messages, tools):
        self.budget.record(stage, 1, 1)
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        if len(messages) == 1:
            self.prompts.append(messages[0]["content"])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def complete(self, stage, system, prompt, schema):
        self.budget.record(stage, 1, 1)
        if stage.startswith("review") and self.reviews:
            return self.reviews.pop(0)
        return MOCK.complete(stage, system, prompt, schema)


def submit(design=None, uid="f1"):
    return reply(use("finish", {"elements": ELEMENTS, "design": design or DESIGN}, uid))


def self_check(uid="c1"):
    return reply(use("check_design", {"elements": ELEMENTS, "design": DESIGN}, uid))


# ---------------------------------------------------------------------------
# 设计自检规则（纯代码）
# ---------------------------------------------------------------------------

def test_mock_design_passes_hard_checks():
    errors, _warnings = check_design(ELEMENTS, DESIGN, EXTRACT_DESTRUCTIVE, [])
    assert errors == []


def test_missing_degradation_scene_is_an_error():
    design = {**DESIGN, "security_and_degradation": ["工具失败 → 重试一次", "超时 → 中断"]}
    errors, _ = check_design(ELEMENTS, design, {}, [])
    assert any("模型幻觉" in e for e in errors) and any("越权" in e for e in errors)


def test_concrete_tool_failure_counts_as_covered():
    design = {**DESIGN, "security_and_degradation": [
        "玩具识别失败或返回空清单 → 提示家长重拍", "模型编造照片外的玩具 → 回退重写",
        "识别或生成超时 → 中止并提示重试", "越权请求保存照片 → 默认拒绝并记审计"]}
    assert check_design(ELEMENTS, design, {}, [])[0] == []


def test_destructive_needs_an_ask_or_deny_tool():
    design = copy.deepcopy(DESIGN)
    for t in design["tool_list"]:
        t["permission"] = "allow"
    errors, warnings = check_design(ELEMENTS, design, EXTRACT_DESTRUCTIVE, [])
    assert any("ask 或 deny" in e for e in errors)
    assert any("save_result" in w and "allow" in w for w in warnings)
    assert not any("ask 或 deny" in e for e in check_design(ELEMENTS, design, {}, [])[0])


@pytest.mark.parametrize("tools, problem", [
    ([], "3 到 8 个"),
    ([{"name": "Fetch Input", "layer": "⑤"}] * 3, "snake_case"),
    ([{"name": "a", "layer": "⑤"}, {"name": "a", "layer": "⑤"}, {"name": "b", "layer": "第五层"}], "重复"),
    ([{"name": "a", "layer": "⑤"}, {"name": "b", "layer": "⑤"}, {"name": "c", "layer": "第五层"}], "layer"),
])
def test_tool_list_shape_errors(tools, problem):
    errors, _ = check_design(ELEMENTS, {**DESIGN, "tool_list": tools}, {}, [])
    assert any(problem in e for e in errors)


def test_testing_and_run_config_are_required():
    design = {**DESIGN, "testing": ["跑一遍看看"], "tech_stack_and_deployment": "单进程 Python"}
    errors, _ = check_design(ELEMENTS, design, {}, [])
    assert sum("testing" in e for e in errors) == 2
    assert any("怎么启动" in e for e in errors) and any("密钥怎么外置" in e for e in errors)


def test_numbers_missing_from_input_are_flagged():
    design = {**DESIGN, "security_and_degradation": DESIGN["security_and_degradation"] + ["生成超时 20 秒 → 重试 3 次"]}
    _, warnings = check_design(ELEMENTS, design, {}, [], input_text="一次读 30 页论文，超时重试 3 次")
    flagged = next(w for w in warnings if "原始输入里没有" in w)
    assert "20 秒" in flagged and "3 次" not in flagged


def test_must_have_component_without_trace_only_warns():
    decisions = [{"id": "s09", "name": "记忆系统", "decision": "必选"}]
    design = {**DESIGN, "context_memory_strategy": "会话内保留完整消息。"}
    errors, warnings = check_design(ELEMENTS, design, {}, decisions)
    assert errors == [] and any("s09" in w for w in warnings)


# ---------------------------------------------------------------------------
# 接进 run_plan
# ---------------------------------------------------------------------------

def test_plan_uses_agent_design(tmp_path):
    runner = ScriptRunner([reply(use("component_card", {"id": "s03"}, "k1")), self_check(), submit()])
    plan, doc = run_plan(IDEA, runner, tmp_path, log=quiet)
    assert plan.design_mode == "agent" and plan.design == DESIGN and plan.elements == ELEMENTS
    card = runner.seen[1][-1]["content"][0]["content"]
    assert card.startswith("s03 权限系统")
    report = runner.seen[2][-1]["content"][0]["content"]
    assert "没有发现问题" in report or "建议看看" in report
    assert "由 agent 完成" in doc.read_text(encoding="utf-8")
    saved = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert saved["design_mode"] == "agent"


def test_finish_with_hard_problem_is_sent_back(tmp_path):
    broken = {**DESIGN, "security_and_degradation": ["超时 → 中断"]}
    runner = ScriptRunner([submit(broken, "f1"), submit(uid="f2")])
    plan, _ = run_plan(IDEA, runner, tmp_path, log=quiet)
    assert plan.design == DESIGN
    assert "越权" in runner.seen[1][-1]["content"][0]["content"]


def test_review_failure_reruns_agent_with_feedback(tmp_path):
    bad = {"ok": False, "issues": [{"section": "工具清单", "problem": "工具与五要素对不上", "severity": "high"}],
           "summary": "x"}
    good = {"ok": True, "issues": [], "summary": "y"}
    runner = ScriptRunner([submit(uid="f1"), submit(uid="f2")], reviews=[bad, good])
    plan, _ = run_plan(IDEA, runner, tmp_path, log=quiet)
    assert plan.design_attempts == 2 and plan.review["ok"]
    assert "工具与五要素对不上" in runner.prompts[1] and "工具与五要素对不上" not in runner.prompts[0]


def test_agent_failure_falls_back_to_fixed_steps(tmp_path):
    runner = ScriptRunner([RuntimeError("tools not supported")])
    plan, doc = run_plan(IDEA, runner, tmp_path, log=quiet)
    assert plan.design_mode == "fixed" and "agent 未完成" in plan.design_note
    assert plan.design == DESIGN and (tmp_path / "stages/model.json").exists()
    assert "⚠️ 领域建模与架构设计用的是固定流程" in doc.read_text(encoding="utf-8")


def test_small_budget_uses_fixed_steps(tmp_path):
    runner = ScriptRunner([], max_calls=6)
    plan, _ = run_plan(IDEA, runner, tmp_path, log=quiet)
    assert plan.design_mode == "fixed" and "调用次数太少" in plan.design_note


def test_resume_reuses_agent_design(tmp_path):
    run_plan(IDEA, ScriptRunner([submit()]), tmp_path, log=quiet)
    again = ScriptRunner([])
    logs = []
    plan, _ = run_plan(IDEA, again, tmp_path, resume=True, log=logs.append)
    assert plan.design_mode == "agent" and again.seen == []
    assert any("④ 领域建模 + 架构设计（agent）：沿用上次结果" in line for line in logs)


def test_mock_runner_keeps_fixed_steps_without_warning(tmp_path):
    plan, doc = run_plan(IDEA, MockRunner(), tmp_path, log=quiet)
    assert plan.design_mode == "fixed" and plan.design_note == ""
    assert "固定流程" not in doc.read_text(encoding="utf-8")
