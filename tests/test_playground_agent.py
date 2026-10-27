"""试玩 agent 的离线测试：三种权限由代码处理、方案外工具调不了、文字直接当回复、退回一次调用写法。"""
import json

import pytest

from blueprint import chat, playground
from blueprint.llm import Budget

PLAN = {"facts": {"users": {"value": "来买面包的顾客"}}, "design": {
    "system_prompt": "你是面包店的店员助手。查菜单回答顾客；下单要店主确认；不能改价。",
    "tool_list": [
        {"name": "lookup_menu", "input": "要查的面包", "output": "面包和价格", "side_effect": "无", "permission": "allow"},
        {"name": "place_order", "input": "订单内容", "output": "订单号", "side_effect": "生成订单", "permission": "ask"},
        {"name": "change_price", "input": "新价格", "output": "改价结果", "side_effect": "改价", "permission": "deny"},
    ],
    "security_and_degradation": ["改价请求 → 拒绝"]}}


def use(name, args, uid):
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


def reply(*blocks, stop="tool_use"):
    return {"content": list(blocks), "stop_reason": stop}


def say(text):
    return reply({"type": "text", "text": text}, stop="end_turn")


class ScriptRunner:
    name = "script"

    def __init__(self, script):
        self.script = list(script)
        self.budget = Budget(max_calls=12, max_tokens=150_000)
        self.systems: list[str] = []
        self.tools: list[list[str]] = []
        self.seen: list[list[dict]] = []

    def step(self, stage, system, messages, tools):
        self.budget.record(stage, 1, 1)
        self.systems.append(system)
        self.tools.append([t["name"] for t in tools])
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class PlayModel:
    def __init__(self, script):
        self.runner = ScriptRunner(script)
        self.sim_prompts: list[str] = []
        self._mock = chat.MockChat()

    def complete_json(self, stage, prompt, schema):
        if stage == "chat_play_tool":
            self.sim_prompts.append(prompt)
            return {"result": "全麦吐司 18 元、可颂 9 元"}
        return self._mock.complete_json(stage, prompt, schema)

    def stream(self, prompt):
        return self._mock.stream(prompt)


@pytest.fixture(autouse=True)
def agent_default(monkeypatch):
    monkeypatch.delenv("BLUEPRINT_PLAY_AGENT", raising=False)       # 默认就是 agent 版


def run(model, text="有什么面包？"):
    return list(playground.play_events(PLAN, [chat.Message("user", text)], "# 面包店\n只卖当天现烤的面包", model))


def steps(events):
    return [e["data"] for e in events if e.get("name") == "play_step"]


def reply_text(events):
    return "".join(e["delta"] for e in events if e["type"] == "text")


def test_allow_tool_result_comes_from_world_simulator():
    model = PlayModel([reply(use("lookup_menu", {"input": "今天的面包"}, "t1")), say("今天有全麦吐司和可颂。")])
    events = run(model)
    assert steps(events) == [{"kind": "tool", "tool": "lookup_menu", "input": "今天的面包",
                              "result": "全麦吐司 18 元、可颂 9 元",
                              "wire": "【模拟·调用 lookup_menu】输入：今天的面包；结果：全麦吐司 18 元、可颂 9 元"}]
    assert reply_text(events) == "今天有全麦吐司和可颂。"
    assert "只卖当天现烤的面包" in model.sim_prompts[0]                        # 外部世界看得到需求文档
    assert "只卖当天现烤的面包" not in model.runner.systems[0]                 # Agent 本身只拿方案里的提示词
    assert model.runner.systems[0].startswith("你是面包店的店员助手")
    assert events[-1] == {"type": "data", "name": "play_feedback", "data": {}}


def test_ask_tool_is_not_executed_and_shows_ask_card():
    model = PlayModel([reply(use("place_order", {"input": "两个可颂", "who_confirms": "店主"}, "t1")),
                       say("已经帮您提交，等店主确认。")])
    events = run(model, "我要两个可颂")
    assert steps(events)[0]["kind"] == "ask_owner" and steps(events)[0]["who"] == "店主"
    told = model.runner.seen[1][-1]["content"][0]["content"]
    assert "确认之前不能当作这件事已经做完" in told and model.sim_prompts == []


def test_deny_tool_is_blocked_by_code():
    model = PlayModel([reply(use("change_price", {"input": "可颂改 5 元"}, "t1")), say("抱歉，价格我改不了。")])
    events = run(model, "可颂便宜点吧")
    assert steps(events)[0]["kind"] == "blocked" and "change_price" in steps(events)[0]["rule"]
    assert "禁止（deny）" in model.runner.seen[1][-1]["content"][0]["content"]


def test_block_request_tool_shows_rule():
    model = PlayModel([reply(use("block_request", {"rule": "不能私下打折"}, "t1")), say("这个我做不了主。")])
    assert steps(run(model, "给我打个折"))[0] == {"kind": "blocked", "rule": "不能私下打折",
                                                 "wire": "【模拟·按规则拦下】不能私下打折"}


def test_only_plan_tools_are_offered_and_unknown_tool_fails_softly():
    model = PlayModel([reply(use("send_coupon", {"input": "x"}, "t1")), say("好的。")])
    events = run(model)
    assert model.runner.tools[0] == ["lookup_menu", "place_order", "change_price", "block_request", "finish"]
    assert steps(events) == []
    assert "没有叫 send_coupon 的工具" in model.runner.seen[1][-1]["content"][0]["content"]


def test_long_inputs_are_clipped_on_cards():
    script = "第一幕" + "小熊过河" * 30
    model = PlayModel([reply(use("lookup_menu", {"input": script}, "t1")), say("好。")])
    card = steps(run(model))[0]
    assert len(card["input"]) == 41 and card["input"].endswith("…") and script in model.sim_prompts[0]


def test_simulation_skipped_when_budget_nearly_spent():
    model = PlayModel([reply(use("lookup_menu", {"input": "面包"}, "t1")), say("好。")])
    model.runner.budget.max_calls = 3
    card = steps(run(model))[0]
    assert "没有模拟" in card["result"] and model.sim_prompts == []


def test_finish_reply_and_empty_reply():
    model = PlayModel([reply(use("finish", {"reply": ""}, "f1"))])
    assert reply_text(run(model, "（假设店主同意了）")) == "（它这一轮没有对你说话）"


def test_agent_failure_falls_back_to_scripted_turn():
    model = PlayModel([RuntimeError("tools not supported")])
    events = run(model)
    assert "离线演示" in reply_text(events)          # MockChat 的一次调用写法


def test_mock_chat_uses_scripted_turn():
    events = run(chat.MockChat())
    assert "离线演示" in reply_text(events)


def test_agent_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("BLUEPRINT_PLAY_AGENT", "off")
    model = PlayModel([])
    assert "离线演示" in reply_text(run(model)) and model.runner.seen == []


def test_cards_come_before_reply():
    model = PlayModel([reply(use("lookup_menu", {"input": "面包"}, "t1")), say("有吐司。")])
    kinds = [e.get("name") or e["type"] for e in run(model)]
    assert kinds == ["play_step", "text", "play_feedback"]


def test_failure_after_cards_does_not_replay_the_turn():
    model = PlayModel([reply(use("lookup_menu", {"input": "面包"}, "t1")), RuntimeError("网络断了")])
    events = run(model)
    assert len(steps(events)) == 1 and "没有演完" in reply_text(events) and "离线演示" not in reply_text(events)
