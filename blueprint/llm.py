"""模型调用层：统一的 Runner 接口、费用护栏、JSON 解析与重试。

兼容 Anthropic 官方 API 与 Anthropic-compatible 网关（MiniMax / GLM / Kimi / DeepSeek），
因此不依赖官方独有的结构化输出参数，而是「提示词要求 JSON + 本地 schema 校验 + 一次纠错重试」。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from pathlib import Path

from blueprint.schema import validate

DEFAULT_MODEL = "claude-opus-5"


def load_config() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def has_credentials() -> bool:
    load_config()
    return any(value and not any(marker in value.lower() for marker in ("xxx", "your", "placeholder"))
               for value in (os.getenv("ANTHROPIC_API_KEY", "").strip(),
                             os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()))


class BudgetExceeded(RuntimeError):
    pass


class StageOutputInvalid(RuntimeError):
    pass


@dataclass
class Budget:
    """费用护栏：调用次数和 token 总量任一超限即停。"""

    max_calls: int = 16
    max_tokens: int = 400_000
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    history: list[dict] = field(default_factory=list)

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"已达到调用次数上限 {self.max_calls}")
        if self.input_tokens + self.output_tokens >= self.max_tokens:
            raise BudgetExceeded(f"已达到 token 上限 {self.max_tokens}")

    def record(self, stage: str, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.history.append({"stage": stage, "input_tokens": input_tokens, "output_tokens": output_tokens})

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
        }


class Runner(Protocol):
    name: str

    def complete(self, stage: str, system: str, prompt: str, schema: dict) -> dict: ...


def extract_json(text: str) -> Any:
    """从模型输出里取出第一个 JSON 对象；容忍 ```json 围栏与前后解释文字。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        raise StageOutputInvalid("输出里没有 JSON 对象")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise StageOutputInvalid("JSON 对象未闭合")


class AnthropicRunner:
    """真实模型调用。"""

    name = "anthropic"

    def __init__(self, model: str | None = None, budget: Budget | None = None, client: Any = None,
                 max_tokens: int = 16000):
        from anthropic import Anthropic
        load_config()
        if client is None and not has_credentials():
            raise ValueError("请在 .env 中填写有效的 ANTHROPIC_API_KEY，或使用 --mock 离线预览")
        self.model = model or os.getenv("MODEL_ID") or DEFAULT_MODEL
        self.budget = budget or Budget()
        self.client = client or Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"),
                                         timeout=120.0, max_retries=0)
        self.max_tokens = max_tokens

    def complete(self, stage: str, system: str, prompt: str, schema: dict) -> dict:
        messages = [{"role": "user", "content": prompt}]
        last_errors: list[str] = []
        for _attempt in range(2):
            self.budget.check()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            self.budget.record(stage,
                               getattr(usage, "input_tokens", 0) or 0,
                               getattr(usage, "output_tokens", 0) or 0)
            if getattr(response, "stop_reason", None) == "refusal":
                raise StageOutputInvalid(f"模型拒绝了阶段 {stage} 的请求")
            text = "".join(getattr(b, "text", "") for b in response.content
                           if getattr(b, "type", None) == "text")
            try:
                data = extract_json(text)
            except (StageOutputInvalid, json.JSONDecodeError) as exc:
                last_errors = [str(exc)]
            else:
                last_errors = validate(schema, data)
                if not last_errors:
                    return data
            messages = messages + [
                {"role": "assistant", "content": text or "(空)"},
                {"role": "user", "content": "上一次输出不符合要求：\n- " + "\n- ".join(last_errors)
                 + "\n请只输出一个符合结构的 JSON 对象，不要任何其他文字。"},
            ]
        raise StageOutputInvalid(f"阶段 {stage} 两次输出都不合格式：{last_errors}")
