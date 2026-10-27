"""试玩：让提出想法的人扮演自己产品的使用者，看看按现在的方案，这个 Agent 大概会怎么表现。

这只是演示，不是产品，也不是原型：没有代码文件、不能导出、不进交接包。

默认（_scripted_events）：一次调用编出整轮动作和回复，约 10 秒。

设置环境变量 BLUEPRINT_PLAY_AGENT=on 且模型支持工具时：这个 Agent 以方案里的系统提示词为身份，方案工具清单里的每个工具注册成真工具，由它
自己决定调不调。每次调用由代码按方案里的权限处理——allow 交给另一次模型调用扮演外部世界编一个结果，
ask 不执行、记为「先问人」，deny 不执行、记为「按规则拦下」。它还能调 block_request 声明按规则拒绝。
agent 版的卡片和拦截结果实测与默认写法基本一致，但每句话要多等约 3 倍时间，所以默认关闭（2026-10-27）。

事件格式同 chat.py，另加：
  {"type": "data", "name": "play_step", "data": {...}}       一步模拟动作（调用工具／先问人／拦下）
  {"type": "data", "name": "play_feedback", "data": {}}      回复下方的「这里不对」按钮
每个 play_step 带 wire 字段：前端把它和文字一起发回来，下一轮模型才知道之前调过什么、拿到了什么。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterator

from blueprint.agent import Tool, run_agent, supports_agent
from blueprint.chat import Message, _prd_context, transcript
from blueprint.knowledge import load_prompt
from blueprint.llm import BudgetExceeded

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
AGENT_TURNS = 5
CARD_INPUT_CHARS = 40          # 卡片给提出想法的人看：Agent 常把整份剧本、整段 JSON 当输入传，只显示开头
SIM_RESERVE_CALLS = 2          # 给 Agent 回复使用者留的调用次数；不够了就不再模拟工具结果
SIM_SCHEMA = {"type": "object", "required": ["result"], "properties": {"result": {"type": "string"}}}
REPLY_SCHEMA = {"type": "object", "required": ["reply"], "properties": {"reply": {"type": "string"}}}


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
    runner = getattr(model, "runner", None)
    if os.getenv("BLUEPRINT_PLAY_AGENT", "").strip().lower() in ("on", "1", "true") and supports_agent(runner):
        try:
            steps, reply = _agent_turn(design, messages, prd, model)
        except (BudgetExceeded, ValueError):
            raise
        except Exception:  # noqa: BLE001 —— agent 失败不能让试玩卡住，这一轮退回一次调用的写法
            pass
        else:
            yield from _turn_events(steps, reply)
            return
    yield from _scripted_events(design, messages, prd, model)


def _turn_events(steps: list[dict], reply: str) -> Iterator[dict]:
    for step in steps:
        yield {"type": "data", "name": "play_step", "data": step}
    # 旁白之后它可能这一轮不说话；直接留空界面上像是卡住了，明说一句
    yield {"type": "text", "delta": reply.strip() or "（它这一轮没有对你说话）"}
    yield {"type": "data", "name": "play_feedback", "data": {}}


def _agent_turn(design: dict, messages: list[Message], prd: str, model) -> tuple[list[dict], str]:
    """跑一轮：Agent 按方案真的调用工具，代码按权限处理每次调用。返回 (界面卡片, 回复)。"""
    tools = _tools(design)
    names = {t["name"] for t in tools}
    steps: list[dict] = []
    history = transcript(messages)

    def record(step: dict) -> None:
        clean = _clean_step(step, names)
        if clean:
            steps.append(clean)

    def make_handler(tool: dict):
        def handle(args: dict) -> str:
            given = str(args.get("input", "")).strip()
            shown = given if len(given) <= CARD_INPUT_CHARS else given[:CARD_INPUT_CHARS] + "…"
            if tool["permission"] == "deny":
                record({"kind": "blocked", "rule": f"{tool['name']} 在方案里是禁止的操作，没有执行"})
                return "这个操作被方案的权限规则禁止（deny），没有执行。"
            if tool["permission"] == "ask":
                who = str(args.get("who_confirms", "")).strip() or "负责人"
                record({"kind": "ask_owner", "who": who, "action": f"{tool['name']}：{shown}"})
                return (f"已提交给{who}确认，对方还没回复。确认之前不能当作这件事已经做完，"
                        "也不要向使用者保证结果。")
            budget = model.runner.budget
            if budget.calls >= budget.max_calls - SIM_RESERVE_CALLS:
                result = "（这次试玩的调用次数快用完了，这一步的结果没有模拟）"
            else:
                result = model.complete_json("chat_play_tool", load_prompt("chat_play_tool").format(
                    tool=json.dumps(tool, ensure_ascii=False), given=given, prd=_prd_context(prd),
                    transcript=history), SIM_SCHEMA)["result"].strip()
            record({"kind": "tool", "tool": tool["name"], "input": shown, "result": result})
            return result
        return handle

    def block(args: dict) -> str:
        record({"kind": "blocked", "rule": str(args.get("rule", "")).strip()})
        return "已记录。接下来告诉使用者为什么不能这么做。"

    agent_tools = []
    for tool in tools:
        if tool["name"] in ("finish", "block_request"):
            continue
        props = {"input": {"type": "string", "description": tool["input"] or "这次要传的内容"}}
        if tool["permission"] == "ask":
            props["who_confirms"] = {"type": "string", "description": "要请谁确认，例如店主、用户本人"}
        agent_tools.append(Tool(
            tool["name"], f"{tool['output']}。副作用：{tool['side_effect'] or '无'}。权限：{tool['permission']}",
            {"type": "object", "required": ["input"], "properties": props}, make_handler(tool)))
    agent_tools.append(Tool("block_request", "使用者要你做越过规则或红线的事、你决定拒绝时调用，写清触发了哪条规则。",
                            {"type": "object", "required": ["rule"], "properties": {"rule": {"type": "string"}}},
                            block))
    result = run_agent("chat_play_agent", load_prompt("chat_play_agent").format(system_prompt=design["system_prompt"]),
                       load_prompt("chat_play_turn").format(transcript=history), agent_tools, REPLY_SCHEMA,
                       model.runner, log=lambda _m: None, max_turns=AGENT_TURNS,
                       text_result=lambda text: {"reply": text},
                       finish_description="把这一轮要对使用者说的话交出来（reply）；也可以不调用它、直接用文字回复。",
                       last_turn_hint="这一轮的动作到此为止，请直接回复使用者。")
    return steps, str(result.get("reply") or "")


def _scripted_events(design: dict, messages: list[Message], prd: str, model) -> Iterator[dict]:
    """一次调用编出整轮动作和回复：默认写法；agent 版失败时也退回这里。"""
    tools = _tools(design)
    prompt = load_prompt("chat_play").format(
        system_prompt=design["system_prompt"],
        tools=json.dumps(tools, ensure_ascii=False, indent=1),
        rules="\n".join(f"- {r}" for r in design.get("security_and_degradation") or []) or "（无）",
        prd=_prd_context(prd), transcript=transcript(messages))
    turn = model.complete_json("chat_play", prompt, TURN_SCHEMA)
    names = {t["name"] for t in tools}
    steps = [step for raw in turn.get("steps") or []
             if isinstance(raw, dict) and (step := _clean_step(raw, names))]
    yield from _turn_events(steps, str(turn.get("reply") or ""))
