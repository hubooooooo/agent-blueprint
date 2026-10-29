"""特征多数票的离线测试：剧本假模型决定另外两票投什么，不花钱。"""
import json
from pathlib import Path

import pytest

from blueprint import vote
from blueprint.forward import run_plan
from blueprint.knowledge import FEATURES
from blueprint.llm import Budget
from blueprint.mock import MockRunner
from blueprint.reverse import run_audit
from blueprint.schema import FACT_IDS
from blueprint.workspace import quick_reselect

ROOT = Path(__file__).resolve().parents[1]
MINIMAL_BOT = ROOT / "evals/reverse/minimal-bot"
IDEA = "一个帮家长给孩子编睡前故事的工具，一次生成一个故事，不能出现暴力内容。"


def feats(**values):
    base = {f.id: {"value": "no", "evidence": "原判断"} for f in FEATURES}
    base.update({k: {"value": v, "evidence": f"票：{v}"} for k, v in values.items()})
    return base


class VoteRunner:
    """另外两票按 ballots 依次返回；其余阶段交给 MockRunner；step() 按剧本。"""

    name = "script"

    def __init__(self, ballots, script=(), max_calls=40):
        self.ballots = list(ballots)
        self.script = list(script)
        self.budget = Budget(max_calls=max_calls, max_tokens=10_000_000)
        self.stages: list[str] = []
        self.seen: list[list[dict]] = []

    def step(self, stage, system, messages, tools):
        self.budget.record(stage, 1, 1)
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        return self.script.pop(0)

    def complete(self, stage, system, prompt, schema):
        self.budget.record(stage, 1, 1)
        self.stages.append(stage)
        if stage.startswith("vote_features"):
            return {"features": self.ballots.pop(0)}
        return MockRunner().complete(stage, system, prompt, schema)


# ---------------------------------------------------------------------------
# 计票
# ---------------------------------------------------------------------------

def test_majority_overrules_a_single_outlier_and_keeps_its_evidence():
    voted, changes = vote.majority(feats(multi_step="yes"), [feats(), feats()])
    assert voted["multi_step"] == {"value": "no", "evidence": "原判断"}
    assert changes == ["multi_step：yes → no（yes / no / no）"]


def test_original_judgment_wins_when_majority_agrees():
    voted, changes = vote.majority(feats(multi_step="yes"), [feats(multi_step="yes"), feats()])
    assert voted["multi_step"]["evidence"] == "票：yes" and changes == []


def test_three_different_values_become_unknown():
    voted, changes = vote.majority(feats(multi_step="yes"), [feats(multi_step="later"), feats()])
    assert voted["multi_step"]["value"] == "unknown"
    assert "各不相同" in voted["multi_step"]["evidence"]
    assert changes == ["multi_step：yes → unknown（yes / later / no）"]


def test_missing_feature_in_a_ballot_counts_as_unknown():
    other = feats()
    del other["multi_step"]
    voted, _ = vote.majority(feats(multi_step="yes"), [other, feats(multi_step="unknown")])
    assert voted["multi_step"]["value"] == "unknown"


def test_prompt_reuses_extract_rules_and_carries_material():
    prompt = vote.feature_prompt("我的点子")
    assert "## 特征问题" in prompt and "destructive_ops" in prompt and "later：" in prompt
    assert "## 待确认清单" not in prompt and "<input>\n我的点子\n</input>" in prompt


def test_disabled_for_mock_env_switch_and_small_budget(monkeypatch):
    assert not vote.enabled(MockRunner())
    assert vote.enabled(VoteRunner([]))
    assert not vote.enabled(VoteRunner([], max_calls=9))
    monkeypatch.setenv("BLUEPRINT_VOTE", "off")
    assert not vote.enabled(VoteRunner([]))


# ---------------------------------------------------------------------------
# 正向推导
# ---------------------------------------------------------------------------

def _mock_features(text=IDEA):
    return MockRunner().complete("extract", "", f"<input>\n{text}\n</input>", {})["features"]


def test_plan_takes_majority_before_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("BLUEPRINT_AGENT", "off")
    base = {k: v["value"] for k, v in _mock_features().items()}
    flipped = "yes" if base["multi_step"] != "yes" else "no"
    other = {k: {"value": v, "evidence": ""} for k, v in base.items()} | {"multi_step": {"value": flipped, "evidence": "两票"}}
    runner = VoteRunner([other, other])
    plan, _ = run_plan(IDEA, runner, tmp_path, log=lambda _m: None)
    assert runner.stages[:3] == ["extract", "vote_features_1", "vote_features_2"]
    assert plan.extract["features"]["multi_step"]["value"] == flipped
    saved = json.loads((tmp_path / "stages/vote_features.json").read_text(encoding="utf-8"))
    assert saved["changes"] == [f"multi_step：{base['multi_step']} → {flipped}（{base['multi_step']} / {flipped} / {flipped}）"]


def test_plan_resume_reuses_ballots(tmp_path, monkeypatch):
    monkeypatch.setenv("BLUEPRINT_AGENT", "off")
    same = _mock_features()
    run_plan(IDEA, VoteRunner([same, same]), tmp_path, log=lambda _m: None)
    again = VoteRunner([])
    run_plan(IDEA, again, tmp_path, resume=True, log=lambda _m: None)
    assert not any(s.startswith("vote_features") for s in again.stages)


def test_no_vote_when_every_feature_is_carried_over(tmp_path):
    runner = VoteRunner([])
    quick_reselect(IDEA, runner, tmp_path, log=lambda _m: None, feature_overrides=feats())
    assert runner.stages == ["extract"]


def test_quick_reselect_votes_like_run_plan(tmp_path):
    same = _mock_features()
    runner = VoteRunner([same, same])
    quick_reselect(IDEA, runner, tmp_path, log=lambda _m: None, feature_overrides={"multi_step": {"value": "no"}})
    assert runner.stages == ["extract", "vote_features_1", "vote_features_2"]


# ---------------------------------------------------------------------------
# 反向检查
# ---------------------------------------------------------------------------

def _use(name, args, uid):
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


def _finish(components, uid):
    intent = {"title": "minimal-bot", "one_liner": "运维命令行助手", "product_summary": "调用 shell 的助手",
              "facts": {k: {"value": "x", "status": "待确认"} for k in FACT_IDS},
              "features": feats(), "unknowns": []}
    return {"content": [_use("finish", {"intent": intent, "components": components}, uid)], "stop_reason": "tool_use"}


def test_audit_with_prd_votes_on_prd_not_agent(tmp_path):
    loop = {"strength": "strong", "evidence": [{"file": "src/bot.py", "line": 16, "note": "while True 调模型"}]}
    same = _mock_features("运维命令行助手，帮工程师执行 shell 命令。")
    components = {f"s{i:02d}": {"strength": "none", "evidence": []} for i in range(1, 18)} | {"s01": loop}
    runner = VoteRunner([same, same], script=[
        {"content": [_use("read_file", {"path": "src/bot.py"}, "r")], "stop_reason": "tool_use"},
        _finish(components, "f1")])
    run_audit(MINIMAL_BOT, runner, tmp_path / "out", prd_text="运维命令行助手，帮工程师执行 shell 命令。",
              log=lambda _m: None)
    assert runner.stages[:3] == ["extract", "vote_features_1", "vote_features_2"]
    assert runner.stages.count("vote_features_1") == 1


def test_audit_without_prd_does_not_vote(tmp_path):
    """没给 PRD 时另外两票只能看 agent 的总结，实测反而更不稳，所以不投（见维护手册）。"""
    loop = {"strength": "strong", "evidence": [{"file": "src/bot.py", "line": 16, "note": "while True 调模型"}]}
    components = {f"s{i:02d}": {"strength": "none", "evidence": []} for i in range(1, 18)} | {"s01": loop}
    runner = VoteRunner([], script=[
        {"content": [_use("read_file", {"path": "src/bot.py"}, "r")], "stop_reason": "tool_use"},
        _finish(components, "f1")])
    run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=lambda _m: None)
    assert not any(s.startswith("vote_features") for s in runner.stages)


def test_fast_audit_does_not_vote(tmp_path):
    runner = VoteRunner([])
    run_audit(MINIMAL_BOT, runner, tmp_path / "out", log=lambda _m: None, fast=True)
    assert not any(s.startswith("vote_features") for s in runner.stages)
