"""试玩：让提出想法的人扮演自己产品的使用者，看看按现在的方案，这个 Agent 大概会怎么表现。

这只是演示，不是产品，也不是原型：没有代码文件、不能导出、不进交接包。每一轮由模型按方案里的
系统提示词草案和工具清单扮演这个 Agent；工具不会真的执行，结果由模型编一个合理的值并标明是模拟。
要先经人确认的动作、被红线拦下的请求单独标出来，让人一眼看到边界管不管用。

事件格式同 chat.py，另加：
  {"type": "data", "name": "play_step", "data": {...}}       一步模拟动作（调用工具／先问人／拦下）
  {"type": "data", "name": "play_feedback", "data": {}}      回复下方的「这里不对」按钮
每个 play_step 带 wire 字段：前端把它和文字一起发回来，下一轮模型才知道之前调过什么、拿到了什么。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

from blueprint.chat import Message, _prd_context, transcript
from blueprint.knowledge import load_prompt

INTRO_STAGE = "chat_play_intro"
STEP_KINDS = ("tool", "ask_owner", "blocked")

INTRO_SCHEMA = {
    "type": "object",
    "required": ["role", "scenarios"],
    "properties": {"role": {"type": "string"}, "scenarios": {"type": "array", "items": {"type": "string"}}},
}

TURN_SCHEMA = {
    "type": "object",
    "required": ["steps", "reply"],
    "properties": {
        "steps": {"type": "array", "items": {"type": "object"}},
        "reply": {"type": "string"},
    },
}

TOOL_FIELDS = ("name", "input", "output", "side_effect", "permission")


def _design(plan: dict) -> dict:
    design = plan.get("design") or {}
    if not design.get("system_prompt"):
        raise ValueError("方案里还没有系统提示词，先生成方案再试玩。")
    return design


def _tools(design: dict) -> list[dict]:
    return [{k: t.get(k, "") for k in TOOL_FIELDS} for t in design.get("tool_list", []) if isinstance(t, dict)]


def fingerprint(plan: dict) -> str:
    """方案里决定 Agent 行为的部分（提示词、工具、安全规则）一变，试玩就换一段新的。"""
    design = plan.get("design") or {}
    key = json.dumps([design.get("system_prompt"), _tools(design), design.get("security_and_degradation")],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _users(plan: dict) -> str:
    users = (plan.get("facts") or {}).get("users") or {}
    return users.get("value", "") if isinstance(users, dict) else str(users)


# ---------------------------------------------------------------------------
# 开场：你扮演谁、可以试试说什么（按方案指纹缓存，方案不变不重复花钱）
# ---------------------------------------------------------------------------

def play_intro(plan: dict, ws: Path, model) -> dict:
    design = _design(plan)
    fp = fingerprint(plan)
    cache = ws / "stages" / f"{INTRO_STAGE}.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fp:
            return {"role": cached["role"], "scenarios": cached["scenarios"], "fingerprint": fp}
    except (OSError, ValueError, KeyError):
        pass
    prompt = load_prompt("chat_play_intro").format(
        one_liner=plan.get("one_liner", ""), users=_users(plan), system_prompt=design["system_prompt"],
        tools=json.dumps(_tools(design), ensure_ascii=False, indent=1))
    raw = model.complete_json(INTRO_STAGE, prompt, INTRO_SCHEMA)
    role = str(raw.get("role") or "").strip() or "这个产品的使用者"
    scenarios = [s.strip() for s in raw.get("scenarios", []) if isinstance(s, str) and s.strip()][:4]
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({"fingerprint": fp, "role": role, "scenarios": scenarios},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"role": role, "scenarios": scenarios, "fingerprint": fp}


def intro_text(role: str) -> str:
    return (f"你现在扮演**{role}**。像他们平时那样发一句话试试，我会按方案里的设计来回应。\n\n"
            "查资料、通知别人这类动作都是**模拟**的，结果是编的；要先经人确认、或者按红线拦下的地方会单独标出来。"
            "哪里和你想的不一样，点回复下面的「这里不对」记下来，最后一起带去「加新需求」。")


# ---------------------------------------------------------------------------
# 每一轮：模型扮演 Agent，给出模拟动作和回复
# ---------------------------------------------------------------------------

def _clean_step(step: dict, tool_names: set[str]) -> dict | None:
    kind = step.get("kind")
    if kind not in STEP_KINDS:
        return None
    text = {k: str(step.get(k) or "").strip() for k in ("tool", "input", "result", "action", "who", "rule")}
    if kind == "tool":
        if text["tool"] not in tool_names:      # 方案里没有的工具不许凭空调用
            return None
        wire = f"【模拟·调用 {text['tool']}】输入：{text['input']}；结果：{text['result']}"
    elif kind == "ask_owner":
        wire = f"【模拟·先问{text['who'] or '人'}】{text['action']}"
    else:
        wire = f"【模拟·按规则拦下】{text['rule']}"
    return {"kind": kind, **{k: v for k, v in text.items() if v}, "wire": wire}


def play_events(plan: dict, messages: list[Message], prd: str, model) -> Iterator[dict]:
    design = _design(plan)
    if not any(m.role == "user" and m.text.strip() for m in messages):
        raise ValueError("先以使用者的身份说一句话")
    tools = _tools(design)
    prompt = load_prompt("chat_play").format(
        system_prompt=design["system_prompt"],
        tools=json.dumps(tools, ensure_ascii=False, indent=1),
        rules="\n".join(f"- {r}" for r in design.get("security_and_degradation") or []) or "（无）",
        prd=_prd_context(prd), transcript=transcript(messages))
    turn = model.complete_json("chat_play", prompt, TURN_SCHEMA)
    names = {t["name"] for t in tools}
    for raw in turn.get("steps") or []:
        step = _clean_step(raw, names) if isinstance(raw, dict) else None
        if step:
            yield {"type": "data", "name": "play_step", "data": step}
    reply = str(turn.get("reply") or "").strip()
    # 旁白之后它可能这一轮不说话；直接留空界面上像是卡住了，明说一句
    yield {"type": "text", "delta": reply or "（它这一轮没有对你说话）"}
    yield {"type": "data", "name": "play_feedback", "data": {}}
