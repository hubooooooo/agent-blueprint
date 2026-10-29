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

from blueprint.schema import coerce_stage_output, validate

DEFAULT_MODEL = "claude-sonnet-4-6"   # 与 .env.example、scaffold 保持一致；tests/test_config_consistency.py 守护


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


CACHE_READ_WEIGHT = 0.1     # 命中缓存的单价：Anthropic 原价 1/10，DeepSeek v4-flash 1/50；按贵的算，宁可算多


@dataclass
class Budget:
    """费用护栏：调用次数和 token 总量任一超限即停。

    input_tokens 不含命中缓存的输入（接口单独返回），另记在 cache_read_tokens；
    算 token 上限时按 CACHE_READ_WEIGHT 折算，见 spent()。
    """

    max_calls: int = 16
    max_tokens: int = 400_000
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    history: list[dict] = field(default_factory=list)

    def spent(self) -> int:
        return self.input_tokens + self.output_tokens + round(self.cache_read_tokens * CACHE_READ_WEIGHT)

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"已达到调用次数上限 {self.max_calls}")
        if self.spent() >= self.max_tokens:
            raise BudgetExceeded(f"已达到 token 上限 {self.max_tokens}")

    def record(self, stage: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.history.append({"stage": stage, "input_tokens": input_tokens, "output_tokens": output_tokens,
                             "cache_read_tokens": cache_read_tokens})

    def record_usage(self, stage: str, usage: Any) -> int:
        """按接口返回的 usage 记一笔，返回输出 token 数。写入缓存的输入并进 input_tokens（单价约原价 1.25 倍）。"""
        read = lambda key: getattr(usage, key, 0) or 0  # noqa: E731
        output = read("output_tokens")
        self.record(stage, read("input_tokens") + read("cache_creation_input_tokens"), output,
                    read("cache_read_input_tokens"))
        return output

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
        }


def cached_note(budget: dict) -> str:
    """用量行的尾巴：「，另有 N tokens 命中缓存」；没有命中缓存时为空。"""
    n = budget.get("cache_read_tokens", 0) or 0
    return f"，另有 {n} tokens 命中缓存（按 1/{round(1 / CACHE_READ_WEIGHT)} 计入上限）" if n else ""


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
    try:                                   # 字符串里出现裸换行 / 制表符时，宽松模式仍可解析
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    if "{" not in text:
        raise StageOutputInvalid("输出里没有 JSON 对象")
    # 模型偶尔会在 JSON 前面输出一段带花括号的解释；从每个左花括号起各试一次，取第一个能闭合且能解析的。
    last_error = "JSON 对象未闭合（常见原因：字符串里有未转义的英文双引号，或输出被截断）"
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        end = _matching_brace(text, start)
        if end is None:
            continue
        try:
            return json.loads(text[start:end + 1], strict=False)
        except json.JSONDecodeError as exc:
            last_error = f"JSON 语法错误：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）"
    raise StageOutputInvalid(last_error)


def _matching_brace(text: str, start: int) -> int | None:
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
                return i
    return None


class AnthropicRunner:
    """真实模型调用。"""

    name = "anthropic"

    def __init__(self, model: str | None = None, budget: Budget | None = None, client: Any = None,
                 max_tokens: int | None = None):
        from anthropic import Anthropic
        load_config()
        if client is None and not has_credentials():
            raise ValueError("请在 .env 中填写有效的 ANTHROPIC_API_KEY，或使用 --mock 离线预览")
        self.model = model or os.getenv("MODEL_ID") or DEFAULT_MODEL
        self.budget = budget or Budget()
        # 单次请求超时默认 120 秒；经中转的慢模型生成长输出会更久，可用环境变量 BLUEPRINT_TIMEOUT 调大。
        self.client = client or Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"),
                                         timeout=float(os.getenv("BLUEPRINT_TIMEOUT", "120")), max_retries=0)
        # 带思考过程的模型（如 deepseek-v4）思考 token 也计入 max_tokens，长 PRD 时 16000 可能不够；
        # 可用环境变量 BLUEPRINT_MAX_OUTPUT_TOKENS 调大。
        self.max_tokens = max_tokens or int(os.getenv("BLUEPRINT_MAX_OUTPUT_TOKENS", "16000"))
        self.attempts: list[dict] = []      # 最近一次 complete() 的每次尝试：原文、stop_reason、错误，供排障落盘

    def step(self, stage: str, system: str, messages: list[dict], tools: list[dict]) -> Any:
        """agent 循环的一轮：带工具调用模型，原样返回响应。消息历史由 blueprint/agent.py 维护。"""
        self.budget.check()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        self.budget.record_usage(stage, getattr(response, "usage", None))
        if getattr(response, "stop_reason", None) == "refusal":
            raise StageOutputInvalid(f"模型拒绝了阶段 {stage} 的请求")
        return response

    def complete(self, stage: str, system: str, prompt: str, schema: dict) -> dict:
        messages = [{"role": "user", "content": prompt}]
        last_errors: list[str] = []
        self.attempts = []
        max_tokens = self.max_tokens
        format_retries = 0
        truncation_retries = 0
        while True:
            self.budget.check()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            output_tokens = self.budget.record_usage(stage, getattr(response, "usage", None))
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "refusal":
                raise StageOutputInvalid(f"模型拒绝了阶段 {stage} 的请求")
            text = "".join(getattr(b, "text", "") for b in response.content
                           if getattr(b, "type", None) == "text")
            record = {"stage": stage, "stop_reason": stop_reason, "output_tokens": output_tokens,
                      "text": text, "errors": []}
            self.attempts.append(record)
            if stop_reason == "max_tokens":
                record["errors"] = [f"输出被截断（max_tokens={max_tokens}，本次输出 {output_tokens} tokens）"]
                if truncation_retries == 0:          # 带思考过程的模型常见：自动加倍预算再试一次
                    truncation_retries += 1
                    max_tokens *= 2
                    continue
                raise StageOutputInvalid(
                    f"阶段 {stage} 的输出被截断：模型用满了 max_tokens={max_tokens}"
                    f"（含思考过程，已自动加倍重试过一次）。"
                    f"请设置环境变量 BLUEPRINT_MAX_OUTPUT_TOKENS={max_tokens * 2} 后加 --resume 重试。")
            try:
                data = coerce_stage_output(stage, extract_json(text))
            except (StageOutputInvalid, json.JSONDecodeError) as exc:
                last_errors = [f"JSON 解析失败：{exc}"]
            else:
                last_errors = validate(schema, data)
                if not last_errors:
                    return data
            record["errors"] = last_errors
            if format_retries >= 1:
                break
            format_retries += 1
            messages = messages + [
                {"role": "assistant", "content": text or "(空)"},
                {"role": "user", "content": "上一次输出不符合要求：\n- " + "\n- ".join(last_errors)
                 + "\n请重新输出完整的 JSON 对象，并检查：字符串内的英文双引号必须写成 \\\"，"
                   "中文引号用「」；不要输出 Markdown 围栏或任何解释文字；所有必填键都要有。"},
            ]
        raise StageOutputInvalid(f"阶段 {stage} 两次输出都不合格式：{last_errors}")
