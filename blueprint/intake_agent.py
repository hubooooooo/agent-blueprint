"""新建产品的追问 agent：自己判断还缺什么、问几轮，信息够了就整理成需求草稿。

每次用户回复都从整段对话重新判断（对话是无状态的，前端每次发全量）。能不能收尾不交给模型自己说了算：
它先用 check_coverage 把六个维度各写一句，由代码按固定规则判断三项必须信息是否齐全。
"""

from __future__ import annotations

from typing import Callable

from blueprint.agent import Tool, run_agent
from blueprint.knowledge import FACT_KEYS, load_prompt

MAX_ROUNDS = 6                                    # 最多问几轮，问满就只能整理草稿
# 这四项都有了（或用户明确说不确定）才能整理草稿。边界放进来是因为真实测试里，
# 一句话写得长的想法会被直接整理，隐私、费用这类红线一次都没问。
MUST_HAVE = ("goal", "users", "core_loop", "boundaries")
UNSURE = ("不确定", "不知道", "没想好", "还没想", "跳过", "待定", "说不清")
MAX_SUGGESTIONS = 3

_LABEL = {key: text.split("：")[0] for key, text in FACT_KEYS.items()}

COVERAGE_SCHEMA = {
    "type": "object",
    "required": ["facts"],
    "properties": {"facts": {
        "type": "object",
        "required": list(FACT_KEYS),
        "properties": {key: {"type": "string"} for key in FACT_KEYS},
    }},
}

RESPOND_SCHEMA = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"type": "string", "enum": ["ask", "draft"]},
        "question": {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "name": {"type": "string"},
        "idea": {"type": "string"},
    },
}


def coverage(facts: dict) -> dict[str, str]:
    """每个维度：已说明 / 用户不确定 / 缺。规则固定，不调模型。"""
    out = {}
    for key in FACT_KEYS:
        text = str(facts.get(key, "") or "").strip()
        if any(word in text for word in UNSURE):
            out[key] = "用户不确定"
        elif len(text) >= 4:
            out[key] = "已说明"
        else:
            out[key] = "缺"
    return out


def ready(status: dict[str, str]) -> bool:
    return all(status.get(key) != "缺" for key in MUST_HAVE)


def run_intake_agent(transcript_text: str, rounds_asked: int, user_wants_draft: bool, runner,
                     log: Callable[[str], None] = lambda _m: None) -> dict:
    """返回 finish 的参数：{"action": "ask", "question", "suggestions"} 或 {"action": "draft", "name", "idea"}。"""
    forced = user_wants_draft or rounds_asked >= MAX_ROUNDS
    state: dict = {"status": None}

    def check_coverage(args: dict) -> str:
        status = coverage(args.get("facts", {}))
        state["status"] = status
        lines = [f"{_LABEL[key]}：{value}" for key, value in status.items()]
        missing = [_LABEL[key] for key in MUST_HAVE if status[key] == "缺"]
        verdict = ("必须信息（目标、用户、核心闭环、边界）都有了，可以整理草稿；其余维度缺的写进「还没想清楚」。"
                   if not missing else f"还缺必须信息：{'、'.join(missing)}。先问其中最要紧的一项。")
        if forced:
            verdict = "用户要求整理，或已经问满轮数：直接整理草稿，缺的写进「还没想清楚」。"
        return "\n".join(lines + [verdict, f"已经问了 {rounds_asked} 轮，最多 {MAX_ROUNDS} 轮。"])

    def check(result: dict) -> list[str]:
        errors: list[str] = []
        if result["action"] == "ask":
            if forced:
                errors.append("用户已要求整理（或已问满轮数），这一轮只能 action=draft")
            if not str(result.get("question", "")).strip():
                errors.append("action=ask 时 question 不能为空")
            if len(result.get("suggestions") or []) > MAX_SUGGESTIONS:
                errors.append(f"suggestions 最多 {MAX_SUGGESTIONS} 个")
            return errors
        if not str(result.get("name", "")).strip() or not str(result.get("idea", "")).strip():
            errors.append("action=draft 时 name 和 idea 都不能为空")
        if not forced:
            if state["status"] is None:
                errors.append("整理草稿前先调用 check_coverage 盘点信息")
            elif not ready(state["status"]):
                missing = [_LABEL[k] for k in MUST_HAVE if state["status"][k] == "缺"]
                errors.append(f"还缺必须信息（{'、'.join(missing)}），不能整理草稿，请改为 action=ask 追问")
        return errors

    tools = [Tool("check_coverage", "把对话里已知的六个维度各写一句（没提到写空字符串，用户说不确定就写「用户不确定」），"
                                    "返回哪些已覆盖、哪些还缺、能不能整理草稿。", COVERAGE_SCHEMA, check_coverage)]
    prompt = load_prompt("chat_intake_agent").format(
        transcript=transcript_text, rounds=rounds_asked, max_rounds=MAX_ROUNDS,
        forced="是：用户点了「信息够了」或已经问满轮数，这一轮必须整理草稿。" if forced else "否",
        first_time="是" if rounds_asked == 0 else "否")
    return run_agent("chat_intake_agent", load_prompt("chat_system"), prompt, tools, RESPOND_SCHEMA, runner,
                     log=log, max_turns=3, check=check,
                     finish_description="交出这一轮的动作：action=ask 时给一个问题（question）和可选的快捷回答（suggestions）；"
                                        "action=draft 时给产品名（name）和 Markdown 需求草稿（idea）。不合格会被退回。")
