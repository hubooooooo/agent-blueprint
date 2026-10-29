"""网页界面的三段对话：新建产品时的追问、逐题回答方案里的待确认问题、给已有产品加新需求。

无状态：前端每次把整段对话发过来，这里从对话里推出进行到哪一步，所以编辑、重新生成都不会错位。
新建产品的追问由 agent 判断还缺什么、问几轮（blueprint/intake_agent.py）；离线演示或 agent 不可用时，
退回固定三轮。其余两段走到哪一步由代码决定，模型只负责措辞。

两个入口都是生成器，产出事件给网页逐条推送：
  {"type": "text", "delta": "..."}                  一段回复文字
  {"type": "tool", "name": "...", "args": {...}}    让网页弹出一张确认卡片
  {"type": "suggestions", "items": ["..."]}         回复下方的快捷按钮
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol

from blueprint.agent import supports_agent
from blueprint.intake_agent import run_intake_agent
from blueprint.knowledge import load_prompt
from blueprint.llm import BudgetExceeded

FINISH_INTAKE = "信息够了，帮我整理"
FINISH_REVISE = "就这样，帮我整理"
SKIP_INTAKE = "不确定，先跳过"
HELP = "帮我想想"
SKIP = "跳过这题"
SAVE = "先保存已回答的"

# agent 不可用时的固定三轮追问，与 使用引导.md 里「让 AI 分三轮问」一致。
INTAKE_ROUNDS = (
    "给谁用、解决什么问题、怎样算做成（有没有可以衡量的标准）。",
    "用户从输入到拿到结果，中间会经过哪些步骤；需要接哪些外部系统、数据或资料。",
    "什么事绝对不能做（隐私、费用、安全上的红线）；出错了怎么办；有没有需要的专业知识。",
)

REVISE_SCHEMA = {
    "type": "object",
    "required": ["title", "requirement"],
    "properties": {"title": {"type": "string"}, "requirement": {"type": "string"}},
}

SUMMARIZE_SCHEMA = {
    "type": "object",
    "required": ["name", "idea"],
    "properties": {"name": {"type": "string"}, "idea": {"type": "string"}},
}


@dataclass
class Message:
    role: str           # user | assistant
    text: str


def parse_messages(raw) -> list[Message]:
    if not isinstance(raw, list):
        raise ValueError("对话格式不对")
    out = []
    for item in raw:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        out.append(Message(item["role"], str(item.get("text") or "")))
    return out


def transcript(messages: Iterable[Message], skip: tuple[str, ...] = ()) -> str:
    lines = []
    for m in messages:
        text = m.text.strip()
        if not text or text in skip:
            continue
        lines.append(f"{'用户' if m.role == 'user' else '助手'}：{text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 模型：真实调用与离线占位
# ---------------------------------------------------------------------------

class ChatModel(Protocol):
    def stream(self, prompt: str) -> Iterator[str]: ...

    def complete_json(self, stage: str, prompt: str, schema: dict) -> dict: ...


class AnthropicChat:
    """复用引擎的 AnthropicRunner：同一套 .env 配置、费用护栏和 JSON 纠错重试。"""

    def __init__(self, runner=None):
        from blueprint.llm import AnthropicRunner, Budget
        self.runner = runner or AnthropicRunner(budget=Budget(max_calls=4, max_tokens=60_000))
        self.system = load_prompt("chat_system")

    def stream(self, prompt: str) -> Iterator[str]:
        self.runner.budget.check()
        with self.runner.client.messages.stream(
            model=self.runner.model, max_tokens=self.runner.max_tokens, system=self.system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            yield from stream.text_stream
            usage = getattr(stream.get_final_message(), "usage", None)
        self.runner.budget.record_usage("chat", usage)

    def complete_json(self, stage: str, prompt: str, schema: dict) -> dict:
        return self.runner.complete(stage, load_prompt("common_system"), prompt, schema)


class MockChat:
    """离线演示：按固定话术回复，整理草稿时原样拼接用户的话。"""

    QUESTIONS = (
        "明白了。先说说这个产品给谁用？它帮他们解决什么麻烦？怎样算做成了？\n\n"
        "比如：「给小学生家长用，省掉每天编睡前故事的时间，家长愿意连续用一周就算成功」。说不清的可以直接说不知道。",
        "好的。用户从开始用到拿到结果，中间会经过哪些步骤？需要接哪些外部系统或资料？\n\n"
        "比如：「家长拍照上传 → AI 认出玩具 → 生成剧本 → 家长确认后打印」。",
        "最后一个问题：有什么事是绝对不能做的？出错了怎么办？\n\n"
        "比如：「照片不能保存」「生成内容要适合 6 岁孩子，不合适就重写」。",
    )

    def stream(self, prompt: str) -> Iterator[str]:
        if "新需求或改一条规则" in prompt:
            text = ("明白，你想加一条新需求。再确认一点：这个改动做到什么程度算好？\n\n"
                    "比如：「每天早上 8 点前推送，推送内容家长一眼能看懂」。说不清可以直接跳过。")
        elif "这一题" in prompt:
            text = ("A. 先只做最简单的版本 —— 上线快，以后再加。\nB. 第一版就做完整 —— 花的时间更多。\n"
                    "你可以直接回复一个字母，或者说说你自己的想法。")
        else:
            rounds = prompt.count("\n助手：") + prompt.startswith("助手：")
            text = self.QUESTIONS[min(rounds, len(self.QUESTIONS) - 1)]
        for i in range(0, len(text), 12):
            yield text[i:i + 12]

    def complete_json(self, stage: str, prompt: str, schema: dict) -> dict:
        said = [line[3:] for line in prompt.splitlines() if line.startswith("用户：")]
        if stage == "chat_revise":
            return {"title": (said[0] if said else "新需求")[:20], "requirement": "\n\n".join(said) or "（未提及）"}
        if stage == "chat_play_intro":
            return {"role": "这个产品的使用者", "scenarios": ["你好，你能帮我做什么？", "能不能便宜一点？"]}
        if stage == "chat_play":
            return self._play(said[-1] if said else "", prompt)
        name = re.split(r"[，。,.!！?？\s]", said[0] if said else "")[0][:12] or "未命名产品"
        idea = "\n\n".join(said) or "（未提及）"
        return {"name": name, "idea": idea}

    @staticmethod
    def _play(last: str, prompt: str) -> dict:
        if re.search(r"折|便宜|优惠|改价|退款", last):
            return {"steps": [{"kind": "blocked", "rule": "价格类承诺不能自己答应（离线演示）"}],
                    "reply": "这个我做不了主，帮您转给店主看看。"}
        tool = re.search(r'"name": "([^"]+)"', prompt)
        steps = [{"kind": "tool", "tool": tool.group(1), "input": last[:30], "result": "（离线演示的模拟结果）"}] if tool else []
        return {"steps": steps, "reply": f"（离线演示）收到：「{last[:30]}」。真实模型会按方案里的提示词回答。"}


# ---------------------------------------------------------------------------
# 新建产品：agent 追问（不可用时固定三轮）→ 整理成需求草稿
# ---------------------------------------------------------------------------

DRAFT_INTRO = "好，我把你说的整理成了一份需求草稿。看看对不对，可以直接改，确认后就开始推导方案："


def intake_events(messages: list[Message], model: ChatModel) -> Iterator[dict]:
    said = [m.text.strip() for m in messages if m.role == "user"]
    if not said or not said[0]:
        raise ValueError("先说说你的想法")
    runner = getattr(model, "runner", None)
    if supports_agent(runner):
        try:
            result = run_intake_agent(transcript(messages, skip=(FINISH_INTAKE,)),
                                      rounds_asked=sum(1 for m in messages if m.role == "assistant"),
                                      user_wants_draft=said[-1] == FINISH_INTAKE, runner=runner)
        except (BudgetExceeded, ValueError):
            raise
        except Exception:  # noqa: BLE001 —— agent 失败不能卡住用户，这一轮退回固定三轮
            pass
        else:
            yield from _agent_events(result)
            return
    yield from _fixed_intake_events(messages, said, model)


def _agent_events(result: dict) -> Iterator[dict]:
    if result["action"] == "draft":
        yield {"type": "text", "delta": DRAFT_INTRO}
        yield {"type": "tool", "name": "confirm_product",
               "args": {"name": result["name"].strip()[:40], "idea": result["idea"].strip()}}
        return
    text = result["question"].strip()
    for i in range(0, len(text), 12):          # 问题是工具参数，不能边生成边显示，分段推送保持打字感
        yield {"type": "text", "delta": text[i:i + 12]}
    quick = [q.strip()[:30] for q in result.get("suggestions") or [] if q.strip()][:3]
    yield {"type": "suggestions", "items": quick + [SKIP_INTAKE, FINISH_INTAKE]}


def _fixed_intake_events(messages: list[Message], said: list[str], model: ChatModel) -> Iterator[dict]:
    answered = [t for t in said if t != FINISH_INTAKE]
    if said[-1] == FINISH_INTAKE or len(answered) > len(INTAKE_ROUNDS):
        yield from _summarize_intake(messages, model)
        return
    focus = INTAKE_ROUNDS[len(answered) - 1]
    prompt = load_prompt("chat_intake_ask").format(
        transcript=transcript(messages, skip=(FINISH_INTAKE,)), focus=focus)
    for delta in model.stream(prompt):
        yield {"type": "text", "delta": delta}
    yield {"type": "suggestions", "items": [SKIP_INTAKE, FINISH_INTAKE]}


def _summarize_intake(messages: list[Message], model: ChatModel) -> Iterator[dict]:
    yield {"type": "text", "delta": DRAFT_INTRO}
    prompt = load_prompt("chat_intake_summarize").format(
        transcript=transcript(messages, skip=(FINISH_INTAKE, SKIP_INTAKE)))
    draft = model.complete_json("chat_summarize", prompt, SUMMARIZE_SCHEMA)
    yield {"type": "tool", "name": "confirm_product",
           "args": {"name": draft["name"].strip()[:40], "idea": draft["idea"].strip()}}


# ---------------------------------------------------------------------------
# 回答待确认问题：逐题问 → 汇总 → 写进 PRD 并重新推导
# ---------------------------------------------------------------------------

def format_question(questions: list[str], index: int) -> str:
    return f"**第 {index + 1} / {len(questions)} 题**\n\n{questions[index]}"


def answer_intro(questions: list[str], key_count: int = 0) -> str:
    """第一条消息由网页直接显示（不走模型），所以开场白放在这里，前后端共用一份。

    key_count：排在最前面的关键问题有几个（见 blueprint/plain.py 的 priority）。
    """
    key = (f"最前面 {key_count} 个最关键，答完它们就可以点「先保存已回答的」，先按这些重新推导。"
           if 0 < key_count < len(questions) else "")
    return (f"方案里有 {len(questions)} 个还没想清楚的问题，我们一题一题过。{key}"
            "想好的直接回答；拿不准的点「帮我想想」，我给你几个方向；实在不知道就跳过。\n\n"
            + format_question(questions, 0))


_OPTION = re.compile(r"^\s*([A-Ca-c])\s*[.．、。:：)]?\s*$")


def _resolve_option(reply: str, previous: str) -> str:
    """用户在「帮我想想」之后只回了一个字母，把它换成那个选项的原文，免得 PRD 里只留下一个「A」。"""
    m = _OPTION.match(reply)
    if not m:
        return reply
    letter = m.group(1).upper()
    for line in previous.splitlines():
        option = re.match(rf"^\s*{letter}\s*[.．、。:：]\s*(.+)$", line)
        if option:
            return re.split(r"\s*(?:——|--)\s*", option.group(1), maxsplit=1)[0].strip()   # 只记做法，不记代价
    return reply


def answer_state(questions: list[str], messages: list[Message]) -> tuple[int, dict[int, str], str]:
    """回放对话：返回（当前题号, 已回答 {题号: 回答}, 最后一个动作）。"""
    index, answers, action, previous = 0, {}, "", ""
    for m in messages:
        if m.role == "assistant":
            previous = m.text
            continue
        text = m.text.strip()
        if text == HELP:
            action = "help"
        elif text == SAVE:
            action = "save"
        elif text == SKIP:
            action, index = "skip", index + 1
        elif text and index < len(questions):
            answers[index] = _resolve_option(text, previous)
            action, index = "answer", index + 1
    return index, answers, action


def answer_events(questions: list[str], messages: list[Message], prd: str, model: ChatModel) -> Iterator[dict]:
    if not questions:
        raise ValueError("这份方案没有待确认问题")
    index, answers, action = answer_state(questions, messages)
    if action == "help" and index < len(questions):
        prompt = load_prompt("chat_answer_suggest").format(prd=prd, question=questions[index])
        for delta in model.stream(prompt):
            yield {"type": "text", "delta": delta}
        yield {"type": "suggestions", "items": [SKIP, SAVE] if answers else [SKIP]}
        return
    if action == "save" or index >= len(questions):
        if not answers:
            yield {"type": "text", "delta": "你还没有回答任何问题。想回答的时候，随时回到这里接着来。"}
            return
        head = "都问完了。" if index >= len(questions) else "好，先保存到这里。"
        yield {"type": "text", "delta": f"{head}这是你的 {len(answers)} 条回答，确认后写进需求文档，并按新的需求重新推导方案："}
        yield {"type": "tool", "name": "confirm_answers",
               "args": {"answers": [{"question": questions[i], "answer": a} for i, a in sorted(answers.items())]}}
        return
    ack = "跳过。" if action == "skip" else "记下了。"
    yield {"type": "text", "delta": f"{ack}\n\n{format_question(questions, index)}"}
    yield {"type": "suggestions", "items": [HELP, SKIP] + ([SAVE] if answers else [])}


# ---------------------------------------------------------------------------
# 加新需求：最多追问一轮 → 整理成需求变更草稿
# ---------------------------------------------------------------------------

PRD_CONTEXT_LIMIT = 8000


def _prd_context(prd: str) -> str:
    """PRD 太长时只给前面一段：追问和整理只需要知道产品大致做什么、已有哪些规则。"""
    return prd if len(prd) <= PRD_CONTEXT_LIMIT else prd[:PRD_CONTEXT_LIMIT] + "\n\n（后文略）"


def revise_events(messages: list[Message], prd: str, model: ChatModel) -> Iterator[dict]:
    said = [m.text.strip() for m in messages if m.role == "user"]
    if not said or not said[0] or said[0] in (FINISH_REVISE, SKIP_INTAKE):
        raise ValueError("先说说想加什么新需求")
    answered = [t for t in said if t != FINISH_REVISE]
    skip = (FINISH_REVISE,)
    if said[-1] == FINISH_REVISE or len(answered) > 1:
        yield {"type": "text", "delta": "好，我把这次的改动整理成了下面这份草稿。看看对不对，可以直接改；确认后需求文档升一版，并重新推导方案："}
        prompt = load_prompt("chat_revise_summarize").format(
            prd=_prd_context(prd), transcript=transcript(messages, skip=skip + (SKIP_INTAKE,)))
        draft = model.complete_json("chat_revise", prompt, REVISE_SCHEMA)
        yield {"type": "tool", "name": "confirm_revision",
               "args": {"title": draft["title"].strip()[:40], "requirement": draft["requirement"].strip()}}
        return
    prompt = load_prompt("chat_revise_ask").format(prd=_prd_context(prd), transcript=transcript(messages, skip=skip))
    for delta in model.stream(prompt):
        yield {"type": "text", "delta": delta}
    yield {"type": "suggestions", "items": [FINISH_REVISE, SKIP_INTAKE]}
