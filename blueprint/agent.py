"""最小 agent 循环：模型 → 工具调用 → 结果 → 模型，直到模型调用 finish 交卷。

和 Runner.complete() 一样返回一个通过 schema 校验的 dict，所以流程里任何一步都能单独换成 agent。
交卷走 finish 工具而不是「输出一段 JSON」：参数天然是结构化的，本地校验不过就退回去让模型改，
不依赖任何服务商的结构化输出功能。设计见 docs/维护手册.md「反向检查的 agent」一节。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from blueprint.llm import StageOutputInvalid, extract_json
from blueprint.schema import validate

MAX_RESULT_CHARS = 8000
MAX_FINISH_REJECTS = 3
EMPTY_FINISH_HINT = ("finish 收到的参数是空的：参数太长或 JSON 格式有误时，接口会把它整个丢掉。"
                     "请不要再调用 finish，直接在文字回复里输出完整的交卷 JSON（只输出 JSON，不加解释）。")


class AgentFailed(RuntimeError):
    """agent 没能交出合格结果；调用方应退回固定流程写法。"""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], str]      # 返回给模型看的文字；出错就抛异常，循环会把错误写进结果

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def supports_agent(runner: Any) -> bool:
    return callable(getattr(runner, "step", None))


def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _as_dict(block: Any) -> dict:
    if isinstance(block, dict):
        return block
    return block.model_dump(exclude_none=True)


def _clip(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n……（结果过长，已截断；原文共 {len(text)} 字，请缩小范围再查）"


def run_agent(stage: str, system: str, prompt: str, tools: list[Tool], result_schema: dict, runner: Any,
              log: Callable[[str], None] = print, max_turns: int = 30,
              check: Callable[[dict], list[str]] | None = None,
              describe: Callable[[str, dict], str] | None = None,
              transcript: Path | None = None,
              finish_description: str = "调查完成时调用，提交最终结论。参数必须符合给定格式；不合格会被退回。",
              last_turn_hint: str = "轮数或费用已用完。请立即调用 finish，用已掌握的信息交卷。") -> dict:
    """跑一个 agent 循环，返回 finish 的参数。

    check：schema 之外的业务校验（比如证据必须真实），返回错误列表，非空就退回重交。
    describe：把一次工具调用变成一句人话进度；None 时只打印工具名。
    transcript：每轮的模型输出和工具结果写进这个 jsonl，便于排查。
    finish_description：交卷工具的说明，不同场景交的东西不同（结论、下一句话……）。
    last_turn_hint：最后一轮（只剩 finish 可用）时提醒模型的话。
    """
    if not supports_agent(runner):
        raise AgentFailed("当前模型接入方式不支持工具调用")
    finish = {"name": "finish", "description": finish_description, "input_schema": result_schema}
    handlers = {t.name: t for t in tools}
    all_specs = [t.spec() for t in tools] + [finish]
    messages: list[dict] = [{"role": "user", "content": prompt}]
    budget = getattr(runner, "budget", None)
    rejects = 0
    nudged = False

    def judge(args: dict) -> list[str]:
        return validate(result_schema, args) or (check(args) if check else [])
    if transcript:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("", encoding="utf-8")

    for turn in range(1, max_turns + 1):
        last = turn == max_turns or _budget_nearly_spent(budget)
        if last:
            _add_user_text(messages, last_turn_hint)
        response = runner.step(stage, system, messages, [finish] if last else all_specs)
        blocks = list(_get(response, "content", []) or [])
        # 思考过程、文字、工具调用原样放回历史：DeepSeek / MiniMax 的思考模式要求这样
        messages.append({"role": "assistant", "content": [_as_dict(b) for b in blocks]})
        uses = [b for b in blocks if _get(b, "type") == "tool_use"]
        record: dict = {"turn": turn, "stop_reason": _get(response, "stop_reason"),
                        "assistant": [_as_dict(b) for b in blocks], "results": []}

        if not uses:
            # 交卷参数太长时有的接口会丢参数，所以也接受写在文字里的交卷 JSON
            candidate = _text_json(blocks)
            if candidate is not None:
                errors = judge(candidate)
                record["results"].append({"tool": "finish(text)", "errors": errors})
                _append(transcript, record)
                if not errors:
                    log(f"    ✓ 交卷（第 {turn} 轮，文字形式）")
                    return candidate
                rejects += 1
                if rejects >= MAX_FINISH_REJECTS:
                    raise AgentFailed(f"交卷连续 {rejects} 次不合格：{errors[:5]}")
                log(f"    ↺ 交卷不合格，退回重交（{len(errors)} 处问题）")
                messages.append({"role": "user", "content": "交卷不合格，请修正后重新输出完整 JSON：\n- " + "\n- ".join(errors[:20])})
                continue
            _append(transcript, record)
            if nudged or last:
                raise AgentFailed(f"模型没有调用 finish 就结束了（第 {turn} 轮）")
            nudged = True
            messages.append({"role": "user", "content": "请继续调查，或者调用 finish 工具交卷。不要用文字直接回答。"})
            continue

        results = []
        for use in uses:
            name, args, use_id = _get(use, "name"), _get(use, "input"), _get(use, "id")
            if not isinstance(args, dict):
                content = f"错误：参数必须是 JSON 对象，实际是 {args!r}"
            elif name == "finish" and not args:
                rejects += 1
                if rejects >= MAX_FINISH_REJECTS:
                    _append(transcript, record)
                    raise AgentFailed(f"交卷连续 {rejects} 次不合格：参数为空")
                log("    ↺ 交卷参数为空，改为在文字里交卷")
                content = EMPTY_FINISH_HINT
            elif name == "finish":
                errors = judge(args)
                if not errors:
                    record["results"].append({"tool": name, "ok": True})
                    _append(transcript, record)
                    log(f"    ✓ 交卷（第 {turn} 轮）")
                    return args
                rejects += 1
                if rejects >= MAX_FINISH_REJECTS:
                    _append(transcript, record)
                    raise AgentFailed(f"交卷连续 {rejects} 次不合格：{errors[:5]}")
                log(f"    ↺ 交卷不合格，退回重交（{len(errors)} 处问题）")
                content = "交卷不合格，请修正后重新调用 finish：\n- " + "\n- ".join(errors[:20])
            elif name in handlers:
                log("    · " + (describe(name, args) if describe else name))
                try:
                    content = _clip(handlers[name].handler(args))
                except Exception as exc:  # noqa: BLE001 —— 工具报错交给模型处理，不中断循环
                    content = f"错误：{exc}"
            else:
                content = f"错误：没有叫 {name} 的工具"
            # DeepSeek 会忽略 is_error，所以错误一律写进正文
            results.append({"type": "tool_result", "tool_use_id": use_id, "content": content})
            record["results"].append({"tool": name, "input": args, "content": content})
        messages.append({"role": "user", "content": results})
        _append(transcript, record)
        if last:
            raise AgentFailed("轮数或费用用完后仍没有交出合格结果")
    raise AgentFailed(f"{max_turns} 轮内没有交卷")


def _add_user_text(messages: list[dict], text: str) -> None:
    """追加一段用户文字；上一条已是用户消息（工具结果）时并进去，避免连续两条用户消息。"""
    last = messages[-1]
    if last["role"] == "user" and isinstance(last["content"], list):
        last["content"].append({"type": "text", "text": text})
    elif last["role"] == "user":
        last["content"] = f"{last['content']}\n\n{text}"
    else:
        messages.append({"role": "user", "content": text})


def _text_json(blocks: list) -> dict | None:
    text = "".join(_get(b, "text", "") or "" for b in blocks if _get(b, "type") == "text")
    if "{" not in text:
        return None
    try:
        data = extract_json(text)
    except (StageOutputInvalid, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _budget_nearly_spent(budget: Any) -> bool:
    if budget is None:
        return False
    if budget.calls >= budget.max_calls - 1:
        return True
    return budget.input_tokens + budget.output_tokens >= budget.max_tokens * 0.85


def _append(path: Path | None, record: dict) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
