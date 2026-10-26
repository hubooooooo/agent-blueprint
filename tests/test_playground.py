"""试玩（blueprint/playground.py）：模拟动作的清洗、事件顺序、开场缓存，全部离线。"""
import pytest

from blueprint.chat import Message, MockChat
from blueprint.playground import INTRO_STAGE, _clean_step, fingerprint, play_events, play_intro

PLAN = {
    "one_liner": "社区烘焙店的微信助手",
    "facts": {"users": {"value": "附近小区的顾客"}},
    "design": {
        "system_prompt": "你是烘焙店助手，只回答面包和蛋糕预订的问题。",
        "tool_list": [{"name": "get_today_bread_catalog", "input": "日期", "output": "清单", "side_effect": "无",
                       "permission": "allow"}],
        "security_and_degradation": ["打折一律转给店主"],
    },
}


def test_clean_step_keeps_known_tools_and_builds_wire():
    names = {"get_today_bread_catalog"}
    step = _clean_step({"kind": "tool", "tool": "get_today_bread_catalog", "input": "今天", "result": "5 样"}, names)
    assert step["wire"] == "【模拟·调用 get_today_bread_catalog】输入：今天；结果：5 样"
    assert _clean_step({"kind": "tool", "tool": "delete_everything"}, names) is None   # 方案里没有的工具
    assert _clean_step({"kind": "think"}, names) is None
    assert _clean_step({"kind": "ask_owner", "action": "确认预订"}, names)["wire"] == "【模拟·先问人】确认预订"
    assert _clean_step({"kind": "blocked", "rule": "不许打折"}, names)["wire"] == "【模拟·按规则拦下】不许打折"


def test_events_come_as_steps_then_reply_then_feedback():
    events = list(play_events(PLAN, [Message("user", "今天有什么面包")], "PRD", MockChat()))
    assert [e["type"] for e in events] == ["data", "text", "data"]
    assert events[0]["data"]["tool"] == "get_today_bread_catalog"
    assert events[-1]["name"] == "play_feedback"

    blocked = list(play_events(PLAN, [Message("user", "能打个八折吗")], "PRD", MockChat()))
    assert blocked[0]["data"]["kind"] == "blocked"


def test_needs_a_user_message_and_a_designed_plan():
    with pytest.raises(ValueError):
        list(play_events(PLAN, [Message("assistant", "开场白")], "PRD", MockChat()))
    with pytest.raises(ValueError):
        list(play_events({"design": {}}, [Message("user", "你好")], "PRD", MockChat()))


def test_model_silence_is_said_out_loud():
    class Silent(MockChat):
        def complete_json(self, stage, prompt, schema):
            return {"steps": [], "reply": ""}

    events = list(play_events(PLAN, [Message("user", "（假设店主同意了）")], "PRD", Silent()))
    assert events[0] == {"type": "text", "delta": "（它这一轮没有对你说话）"}


def test_intro_is_cached_until_the_agent_design_changes(tmp_path):
    class Counting(MockChat):
        calls = 0

        def complete_json(self, stage, prompt, schema):
            Counting.calls += 1
            return {"role": "来问面包的顾客", "scenarios": ["今天有什么面包？", "  ", 3, "能打折吗？"]}

    first = play_intro(PLAN, tmp_path, Counting())
    assert first["role"] == "来问面包的顾客" and first["scenarios"] == ["今天有什么面包？", "能打折吗？"]
    play_intro(PLAN, tmp_path, Counting())
    assert Counting.calls == 1 and (tmp_path / "stages" / f"{INTRO_STAGE}.json").is_file()

    changed = {**PLAN, "design": {**PLAN["design"], "system_prompt": "改过的提示词"}}
    assert fingerprint(changed) != fingerprint(PLAN)
    play_intro(changed, tmp_path, Counting())
    assert Counting.calls == 2
