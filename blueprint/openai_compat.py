"""OpenAI 格式（Chat Completions）的模型接口，装成 Anthropic 客户端的样子给 AnthropicRunner 用。

引擎按 Anthropic Messages 的格式收发：
消息里有 text / tool_use / tool_result 块，响应有 content、stop_reason、usage。这里只做格式翻译，
其余逻辑（费用护栏、JSON 纠错重试）原样复用。

用 OpenAI 官方接口，或者 OpenAI 格式的中转、DeepSeek / Kimi 的 OpenAI 兼容接口都可以。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

OPENAI_BASE_URL = "https://api.openai.com/v1"

_STOP_REASON = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use",
                "function_call": "tool_use", "content_filter": "refusal"}


class Block(dict):
    """响应里的一个内容块：agent 循环当字典读，complete() 按属性读，两种都支持。"""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


class OpenAIError(RuntimeError):
    pass


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(str(_field(b, "text", "")) for b in content or [] if _field(b, "type") == "text")


def _field(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    """Anthropic 格式的对话历史 → Chat Completions 的 messages。"""
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue
            msg: dict = {"role": "assistant", "content": _text_of(content) or None}
            calls = [{"id": _field(b, "id"), "type": "function",
                      "function": {"name": _field(b, "name"),
                                   "arguments": json.dumps(_field(b, "input", {}), ensure_ascii=False)}}
                     for b in content if _field(b, "type") == "tool_use"]
            if calls:
                msg["tool_calls"] = calls
            # DeepSeek 等思考模型在工具调用过程中要求把思考原样带回；只在接口给过时才带，官方 OpenAI 不会出现
            reasoning = "".join(str(_field(b, "thinking", "")) for b in content if _field(b, "type") == "thinking")
            if reasoning:
                msg["reasoning_content"] = reasoning
            out.append(msg)
            continue
        if isinstance(content, str):
            out.append({"role": "user", "content": content})
            continue
        # 用户消息里的 tool_result 拆成 tool 消息，必须紧跟在发起调用的 assistant 消息后面；其余文字另起一条 user
        for b in content:
            if _field(b, "type") == "tool_result":
                result = _field(b, "content", "")
                out.append({"role": "tool", "tool_call_id": _field(b, "tool_use_id"),
                            "content": result if isinstance(result, str) else _text_of(result)})
        text = _text_of(content)
        if text:
            out.append({"role": "user", "content": text})
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t.get("input_schema", {"type": "object"})}}
            for t in tools]


def from_openai_response(data: dict) -> SimpleNamespace:
    """Chat Completions 的响应 → 有 content / stop_reason / usage 的 Anthropic 风格对象。"""
    choices = data.get("choices") or []
    if not choices:
        raise OpenAIError(f"接口没有返回结果：{str(data)[:300]}")
    choice = choices[0]
    message = choice.get("message") or {}
    blocks: list[Block] = []
    if message.get("reasoning_content"):
        blocks.append(Block(type="thinking", thinking=message["reasoning_content"]))
    if message.get("content"):
        blocks.append(Block(type="text", text=message["content"]))
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = raw                      # 原样交给 agent 循环，它会回一句「参数必须是 JSON 对象」让模型重来
        blocks.append(Block(type="tool_use", id=call.get("id", ""), name=fn.get("name", ""), input=args))
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0   # 后者是 DeepSeek 的写法
    prompt = usage.get("prompt_tokens") or 0
    return SimpleNamespace(
        content=blocks,
        stop_reason=_STOP_REASON.get(choice.get("finish_reason"), choice.get("finish_reason")),
        usage=SimpleNamespace(input_tokens=max(prompt - cached, 0), output_tokens=usage.get("completion_tokens") or 0,
                              cache_read_input_tokens=cached, cache_creation_input_tokens=0),
    )


class _Messages:
    def __init__(self, owner: "OpenAICompatClient"):
        self._owner = owner

    def create(self, *, model: str, max_tokens: int, messages: list[dict], system: str = "",
               tools: list[dict] | None = None) -> SimpleNamespace:
        return self._owner.chat(model=model, max_tokens=max_tokens, system=system, messages=messages, tools=tools)


class OpenAICompatClient:
    """只实现引擎用到的 client.messages.create(...)。"""

    def __init__(self, api_key: str, base_url: str | None = None, timeout: float = 120.0, transport: Any = None):
        import httpx
        self.base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
        self.official = "api.openai.com" in self.base_url
        self._http = httpx.Client(timeout=timeout, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self.messages = _Messages(self)

    def chat(self, *, model: str, max_tokens: int, system: str, messages: list[dict],
             tools: list[dict] | None) -> SimpleNamespace:
        body: dict = {"model": model, "messages": to_openai_messages(system, messages)}
        # OpenAI 官方的新模型只认 max_completion_tokens；兼容接口（DeepSeek、Kimi、中转）普遍只认 max_tokens
        body["max_completion_tokens" if self.official else "max_tokens"] = max_tokens
        if tools:
            body["tools"] = to_openai_tools(tools)
        resp = self._http.post(f"{self.base_url}/chat/completions", json=body)
        if resp.status_code >= 400:
            raise OpenAIError(f"接口返回 {resp.status_code}：{resp.text[:400]}")
        return from_openai_response(resp.json())
