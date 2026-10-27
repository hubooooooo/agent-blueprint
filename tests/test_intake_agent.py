"""新建产品追问 agent 的离线测试：覆盖度规则、何时能整理草稿、退回固定三轮。"""
import json

import pytest

from blueprint import chat
from blueprint.intake_agent import MAX_ROUNDS, coverage, ready, run_intake_agent
from blueprint.llm import Budget

FULL = {"goal": "家长愿意连续用一周", "users": "小学生家长", "core_loop": "拍照 → 识别玩具 → 生成剧本",
        "deliverable": "一份剧本", "boundaries": "照片不保存", "constraints": ""}


def use(name, args, uid):
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


def reply(*blocks):
    return {"content": list(blocks), "stop_reason": "tool_use"}


class ScriptRunner:
    name = "script"

    def __init__(self, script):
        self.script = list(script)
        self.budget = Budget(max_calls=4, max_tokens=60_000)
        self.seen: list[list[dict]] = []

    def step(self, stage, system, messages, tools):
        self.budget.record(stage, 1, 1)
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def coverage_call(facts, uid="c1"):
    return reply(use("check_coverage", {"facts": facts}, uid))


def ask(question="给谁用？", suggestions=None, uid="f1"):
    return reply(use("finish", {"action": "ask", "question": question, "suggestions": suggestions or []}, uid))


def draft(uid="f2"):
    return reply(use("finish", {"action": "draft", "name": "玩具剧场", "idea": "### 一句话想法\n拍照生成剧本"}, uid))


# ---------------------------------------------------------------------------
# 覆盖度规则（不调模型）
# ---------------------------------------------------------------------------

def test_coverage_marks_unsure_and_missing():
    status = coverage({**FULL, "users": "用户不确定", "core_loop": ""})
    assert status["goal"] == "已说明" and status["users"] == "用户不确定" and status["core_loop"] == "缺"
    assert not ready(status)
    assert ready(coverage({**FULL, "core_loop": "还没想好"}))      # 用户说过不确定也算处理过
    assert not ready(coverage({**FULL, "boundaries": ""}))         # 红线没问过不能收尾


# ---------------------------------------------------------------------------
# agent 本身
# ---------------------------------------------------------------------------

def test_complete_idea_goes_straight_to_draft():
    runner = ScriptRunner([coverage_call(FULL), draft()])
    result = run_intake_agent("用户：（完整的想法）", rounds_asked=0, user_wants_draft=False, runner=runner)
    assert result["action"] == "draft" and result["name"] == "玩具剧场"


def test_draft_is_rejected_while_must_have_missing():
    runner = ScriptRunner([coverage_call({**FULL, "users": ""}), draft(), ask("给谁用？", uid="f3")])
    result = run_intake_agent("用户：做个剧本生成器", rounds_asked=1, user_wants_draft=False, runner=runner)
    assert result == {"action": "ask", "question": "给谁用？", "suggestions": []}
    sent_back = runner.seen[2][-1]["content"]
    assert "还缺必须信息（用户）" in sent_back[0]["content"]
    assert sent_back[-1]["type"] == "text" and "轮数或费用已用完" in sent_back[-1]["text"]   # 收尾提醒并进同一条消息


def test_draft_without_coverage_check_is_rejected():
    runner = ScriptRunner([draft("f1"), coverage_call(FULL, "c2"), draft("f3")])
    assert run_intake_agent("用户：x", 0, False, runner)["action"] == "draft"
    assert "先调用 check_coverage" in runner.seen[1][-1]["content"][0]["content"]


@pytest.mark.parametrize("rounds, wants", [(1, True), (MAX_ROUNDS, False)])
def test_forced_rounds_only_allow_draft(rounds, wants):
    runner = ScriptRunner([ask(uid="f1"), draft("f2")])
    assert run_intake_agent("用户：x", rounds, wants, runner)["action"] == "draft"
    assert "只能 action=draft" in runner.seen[1][-1]["content"][0]["content"]


def test_forced_draft_allowed_even_when_info_missing():
    runner = ScriptRunner([coverage_call({k: "" for k in FULL}), draft()])
    assert run_intake_agent("用户：x", 2, True, runner)["action"] == "draft"


# ---------------------------------------------------------------------------
# 接进网页对话
# ---------------------------------------------------------------------------

class AgentChat:
    """带 runner 的聊天模型：走 agent；fallback 时用 MockChat 的固定话术。"""

    def __init__(self, script):
        self.runner = ScriptRunner(script)
        self._mock = chat.MockChat()

    def stream(self, prompt):
        return self._mock.stream(prompt)

    def complete_json(self, stage, prompt, schema):
        return self._mock.complete_json(stage, prompt, schema)


def events(model, *texts):
    msgs = [chat.Message("user" if i % 2 == 0 else "assistant", t) for i, t in enumerate(texts)]
    return list(chat.intake_events(msgs, model))


def test_ask_event_streams_question_and_adds_fixed_buttons():
    question = "明白了，你想做一个给家长用的剧本生成器。它要做到什么程度才算成功？"
    out = events(AgentChat([coverage_call({**FULL, "goal": ""}), ask(question, ["一周内天天用", "不知道"])]), "做个剧本生成器")
    assert "".join(e["delta"] for e in out if e["type"] == "text") == question
    assert out[-1] == {"type": "suggestions", "items": ["一周内天天用", "不知道", chat.SKIP_INTAKE, chat.FINISH_INTAKE]}


def test_draft_event_shows_confirm_card():
    out = events(AgentChat([coverage_call(FULL), draft()]), "完整想法")
    assert out[0]["delta"] == chat.DRAFT_INTRO
    assert out[1] == {"type": "tool", "name": "confirm_product",
                      "args": {"name": "玩具剧场", "idea": "### 一句话想法\n拍照生成剧本"}}


def test_agent_failure_falls_back_to_fixed_rounds():
    out = events(AgentChat([RuntimeError("tools not supported")]), "做个剧本生成器")
    text = "".join(e["delta"] for e in out if e["type"] == "text")
    assert text == chat.MockChat.QUESTIONS[0]


def test_finish_button_tells_agent_to_draft():
    model = AgentChat([draft()])
    out = events(model, "做个剧本生成器", "问题一", chat.FINISH_INTAKE)
    assert out[-1]["name"] == "confirm_product"
    prompt = model.runner.seen[0][0]["content"]
    assert "必须整理草稿：是" in prompt and chat.FINISH_INTAKE not in prompt


def test_mock_chat_keeps_fixed_three_rounds():
    out = events(chat.MockChat(), "做个剧本生成器")
    assert "".join(e["delta"] for e in out if e["type"] == "text") == chat.MockChat.QUESTIONS[0]
