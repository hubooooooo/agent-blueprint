"""模型输出格式的健壮性：宽松解析、截断识别、失败原文落盘、具体错误回喂。"""
import json
from types import SimpleNamespace

import pytest

from blueprint.llm import AnthropicRunner, Budget, StageOutputInvalid, extract_json
from blueprint.schema import EXTRACT_SCHEMA, FEATURE_IDS

FACTS = {k: {"value": "x", "status": "明确", "source": ""} for k in
         ["goal", "users", "core_loop", "deliverable", "boundaries", "constraints"]}
GOOD = json.dumps({"title": "t", "one_liner": "o", "facts": FACTS,
                   "features": {fid: {"value": "no", "evidence": ""} for fid in FEATURE_IDS}, "unknowns": []})


class _FakeClient:
    def __init__(self, texts, stop_reasons=None):
        self._texts = list(texts)
        self._stops = list(stop_reasons or ["end_turn"] * len(texts))
        self.calls: list[list] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw["messages"])
        self.max_tokens_seen = getattr(self, "max_tokens_seen", []) + [kw["max_tokens"]]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._texts.pop(0))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=7),
                               stop_reason=self._stops.pop(0))


def test_extract_json_tolerates_raw_newlines_inside_strings():
    assert extract_json('{"a": "第一行\n第二行"}') == {"a": "第一行\n第二行"}
    assert extract_json('前言 {"a": "x\ty"} 后记') == {"a": "x\ty"}


def test_truncation_retries_once_with_doubled_budget_then_reports(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    client = _FakeClient(['{"title": "截断', '{"title": "又截断'], ["max_tokens", "max_tokens"])
    runner = AnthropicRunner(client=client, budget=Budget(max_calls=5), max_tokens=1000)
    with pytest.raises(StageOutputInvalid, match="BLUEPRINT_MAX_OUTPUT_TOKENS=4000"):
        runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)
    assert client.max_tokens_seen == [1000, 2000]
    assert [a["stop_reason"] for a in runner.attempts] == ["max_tokens", "max_tokens"]


def test_truncation_then_success(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    client = _FakeClient(['{"title": "截断', GOOD], ["max_tokens", "end_turn"])
    runner = AnthropicRunner(client=client, budget=Budget(max_calls=5), max_tokens=1000)
    assert runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)["title"] == "t"
    assert client.max_tokens_seen == [1000, 2000]
    assert len(client.calls[1]) == 1         # 截断重试不追加纠错对话，直接重发原提示


def test_extract_json_skips_prose_braces_before_the_object():
    assert extract_json('先解释一下 {这不是 json} 然后给出 {"a": 1} 完') == {"a": 1}
    with pytest.raises(StageOutputInvalid, match="语法错误|未闭合"):
        extract_json('{"a": 引号"坏了"}')


def test_retry_feedback_is_specific_and_attempts_are_recorded(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    client = _FakeClient(['{"title": "引号"坏了"}', GOOD])
    runner = AnthropicRunner(client=client, budget=Budget(max_calls=3))
    data = runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)
    assert data["title"] == "t"
    feedback = client.calls[1][-1]["content"]
    assert "JSON 解析失败" in feedback and "双引号" in feedback
    assert len(runner.attempts) == 2 and runner.attempts[0]["errors"] and not runner.attempts[1]["errors"]


def test_max_output_tokens_env(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    monkeypatch.setenv("BLUEPRINT_MAX_OUTPUT_TOKENS", "32000")
    assert AnthropicRunner(client=_FakeClient([])).max_tokens == 32000


def test_stage_runner_dumps_failed_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    from blueprint.pipeline import StageRunner
    runner = AnthropicRunner(client=_FakeClient(["不是 json", "还不是"]), budget=Budget(max_calls=3))
    stages = StageRunner(runner, tmp_path, log=lambda _m: None)
    with pytest.raises(StageOutputInvalid):
        stages.run("extract", "prompt", EXTRACT_SCHEMA)
    dump = tmp_path / "stages" / "extract.failed.json"
    assert dump.is_file()
    assert [a["text"] for a in json.loads(dump.read_text(encoding="utf-8"))] == ["不是 json", "还不是"]
