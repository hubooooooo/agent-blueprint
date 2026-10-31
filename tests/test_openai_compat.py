"""OpenAI 格式接口：格式翻译、工具调用往返、用量折算、配置切换。全部离线（httpx.MockTransport）。"""
from __future__ import annotations

import json

import httpx
import pytest

from blueprint import providers
from blueprint.agent import run_agent
from blueprint.llm import AnthropicRunner, Budget
from blueprint.openai_compat import OpenAICompatClient, OpenAIError, to_openai_messages


def _reply(message: dict, finish: str = "stop", usage: dict | None = None) -> dict:
    return {"choices": [{"message": message, "finish_reason": finish}],
            "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20,
                               "prompt_tokens_details": {"cached_tokens": 40}}}


def _client(replies: list[dict], seen: list[dict], base: str | None = "https://relay.example/v1") -> OpenAICompatClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "auth": request.headers["authorization"],
                     "body": json.loads(request.content)})
        return httpx.Response(200, json=replies.pop(0))
    return OpenAICompatClient("sk-test", base, transport=httpx.MockTransport(handler))


def test_complete_returns_json_and_counts_cached_tokens():
    seen: list[dict] = []
    client = _client([_reply({"content": '{"ok": true}'})], seen)
    runner = AnthropicRunner(model="gpt-6-luna", budget=Budget(), client=client)
    data = runner.complete("extract", "系统提示", "给我 JSON", {"type": "object", "required": ["ok"]})
    assert data == {"ok": True}
    req = seen[0]
    assert req["url"] == "https://relay.example/v1/chat/completions" and req["auth"] == "Bearer sk-test"
    assert req["body"]["messages"][0] == {"role": "system", "content": "系统提示"}
    assert "max_tokens" in req["body"] and "max_completion_tokens" not in req["body"]   # 中转只认 max_tokens
    assert runner.budget.input_tokens == 60 and runner.budget.cache_read_tokens == 40   # 命中缓存单独记
    assert runner.budget.output_tokens == 20


def test_official_openai_uses_max_completion_tokens():
    seen: list[dict] = []
    client = _client([_reply({"content": '{"ok": true}'})], seen, base=None)
    AnthropicRunner(model="gpt-6-luna", budget=Budget(), client=client).complete("s", "", "x", {"type": "object"})
    assert seen[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert "max_completion_tokens" in seen[0]["body"] and "max_tokens" not in seen[0]["body"]


def test_agent_tool_round_trip_keeps_pairing_and_reasoning():
    """agent 循环：tool_calls → tool 消息紧跟其后；思考模型的 reasoning_content 原样带回。"""
    seen: list[dict] = []
    replies = [
        _reply({"content": None, "reasoning_content": "先查一下",
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "lookup", "arguments": '{"q": "s03"}'}}]}, "tool_calls"),
        _reply({"content": None, "tool_calls": [{"id": "call_2", "type": "function",
                "function": {"name": "finish", "arguments": '{"answer": "好了"}'}}]}, "tool_calls"),
    ]
    runner = AnthropicRunner(model="deepseek-v4-flash", budget=Budget(), client=_client(replies, seen))
    from blueprint.agent import Tool
    tools = [Tool("lookup", "查资料", {"type": "object", "properties": {"q": {"type": "string"}}},
                  lambda args: f"查到了 {args['q']}")]
    result = run_agent("test", "系统", "开始", tools, {"type": "object", "required": ["answer"],
                       "properties": {"answer": {"type": "string"}}}, runner, log=lambda _m: None, max_turns=4)
    assert result == {"answer": "好了"}
    second = seen[1]["body"]
    assert second["tools"][0]["type"] == "function" and second["tools"][0]["function"]["name"] == "lookup"
    msgs = second["messages"]
    call = next(i for i, m in enumerate(msgs) if m.get("tool_calls"))
    assert msgs[call]["reasoning_content"] == "先查一下"
    assert msgs[call]["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"q": "s03"}'}
    assert msgs[call + 1] == {"role": "tool", "tool_call_id": "call_1", "content": "查到了 s03"}


def test_message_translation_splits_tool_results_from_text():
    msgs = to_openai_messages("", [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": [{"type": "text", "text": "我查一下"},
                                          {"type": "tool_use", "id": "t1", "name": "read", "input": {"p": "a"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "内容"},
                                     {"type": "text", "text": "还剩 2 轮"}]},
    ])
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "user"]
    assert msgs[1]["content"] == "我查一下" and "reasoning_content" not in msgs[1]
    assert msgs[3]["content"] == "还剩 2 轮"


def test_http_error_is_reported_with_status():
    client = OpenAICompatClient("sk", "https://relay.example/v1", transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": {"message": "invalid key"}})))
    with pytest.raises(OpenAIError, match="401"):
        client.messages.create(model="m", max_tokens=8, messages=[{"role": "user", "content": "hi"}])


def test_runner_picks_openai_client_from_env(monkeypatch):
    for name, value in {"API_FORMAT": "openai", "OPENAI_API_KEY": "sk-oa-real-0123456789",
                        "OPENAI_BASE_URL": "https://relay.example/v1", "MODEL_ID": ""}.items():
        monkeypatch.setenv(name, value)
    runner = AnthropicRunner()
    assert runner.name == "openai" and isinstance(runner.client, OpenAICompatClient)
    assert runner.model == "gpt-6-luna" and runner.client.base_url == "https://relay.example/v1"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        AnthropicRunner()


def test_write_env_switches_format_and_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=a\nANTHROPIC_BASE_URL=https://x/anthropic\nBLUEPRINT_TIMEOUT=300\n", encoding="utf-8")
    providers.write_env("sk-oa", "gpt-6-luna", None, path=env, fmt="openai")
    data = providers.read_env(env)
    assert providers.current_config(data) == {"format": "openai", "key": "sk-oa", "base": None, "model": "gpt-6-luna"}
    assert "ANTHROPIC_API_KEY" not in data and data["BLUEPRINT_TIMEOUT"] == "300"
    providers.write_env("sk-ds", "deepseek-v4-flash", "https://api.deepseek.com/anthropic", path=env)
    data = providers.read_env(env)
    assert providers.current_config(data)["format"] == "anthropic" and "API_FORMAT" not in data
