"""OpenAI 格式接口：格式翻译、用量折算、按 .env 选客户端、终端向导写配置。全部离线（httpx.MockTransport）。"""
from __future__ import annotations

import json

import httpx
import pytest

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


def test_complete_returns_json_and_excludes_cached_tokens():
    seen: list[dict] = []
    client = _client([_reply({"content": '{"ok": true}'})], seen)
    runner = AnthropicRunner(model="gpt-6-luna", budget=Budget(), client=client)
    data = runner.complete("extract", "系统提示", "给我 JSON", {"type": "object", "required": ["ok"]})
    assert data == {"ok": True}
    req = seen[0]
    assert req["url"] == "https://relay.example/v1/chat/completions" and req["auth"] == "Bearer sk-test"
    assert req["body"]["messages"][0] == {"role": "system", "content": "系统提示"}
    assert "max_tokens" in req["body"] and "max_completion_tokens" not in req["body"]   # 中转只认 max_tokens
    assert runner.budget.input_tokens == 60     # 命中缓存的 40 不计（v1 的 Anthropic 格式也不计）
    assert runner.budget.output_tokens == 20


def test_official_openai_uses_max_completion_tokens():
    seen: list[dict] = []
    client = _client([_reply({"content": '{"ok": true}'})], seen, base=None)
    AnthropicRunner(model="gpt-6-luna", budget=Budget(), client=client).complete("s", "", "x", {"type": "object"})
    assert seen[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert "max_completion_tokens" in seen[0]["body"] and "max_tokens" not in seen[0]["body"]


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


def test_wizard_writes_openai_config(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location("wizard", _P(__file__).resolve().parents[1] / "tools/wizard.py")
    wizard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wizard)
    monkeypatch.setattr(wizard, "ENV_PATH", tmp_path / ".env")
    wizard.write_env("sk-oa-real-0123456789", "gpt-6-luna", "https://relay.example/v1", fmt="openai")
    env = wizard.read_env()
    assert env == {"API_FORMAT": "openai", "OPENAI_API_KEY": "sk-oa-real-0123456789", "MODEL_ID": "gpt-6-luna",
                   "OPENAI_BASE_URL": "https://relay.example/v1"}
    assert wizard.has_real_key()
    assert {p["format"] for p in wizard.PROVIDERS.values()} == {"anthropic", "openai"}
