"""features 块的健壮性：键名归一化、必填校验、以及真实模型跑偏时不再整份「待确认」。"""
import json
from types import SimpleNamespace

from blueprint.llm import AnthropicRunner, Budget
from blueprint.schema import EXTRACT_SCHEMA, FEATURE_IDS, coerce_stage_output, validate

FACTS = {k: {"value": "x", "status": "明确", "source": ""} for k in
         ["goal", "users", "core_loop", "deliverable", "boundaries", "constraints"]}


def test_component_ids_are_mapped_back_to_feature_ids():
    data = {"features": {"s03": {"value": "yes", "evidence": "删除"}, "S12": "no", "notes": "junk"}}
    out = coerce_stage_output("extract", data)
    assert out["features"] == {"destructive_ops": {"value": "yes", "evidence": "删除"},
                               "scheduled": {"value": "no", "evidence": ""}}


def test_canonical_key_wins_over_alias_and_other_stages_untouched():
    data = {"features": {"destructive_ops": {"value": "no"}, "s03": {"value": "yes"}}}
    assert coerce_stage_output("infer_retry", data)["features"]["destructive_ops"] == {"value": "no"}
    design = {"features": {"s03": {"value": "yes"}}}
    assert coerce_stage_output("design", design) is design


def test_schema_requires_all_fourteen_features():
    partial = {"title": "t", "one_liner": "o", "facts": FACTS,
               "features": {"destructive_ops": {"value": "yes"}}, "unknowns": []}
    errors = validate(EXTRACT_SCHEMA, partial)
    assert any("scheduled" in e for e in errors)
    full = dict(partial, features={fid: {"value": "unknown"} for fid in FEATURE_IDS})
    assert validate(EXTRACT_SCHEMA, full) == []


class _FakeClient:
    def __init__(self, texts):
        self._texts = list(texts)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        text = self._texts.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                               stop_reason="end_turn")


def test_runner_accepts_component_keyed_output_without_retry(monkeypatch):
    """复现真实模型的跑偏输出：键为 s03…s17。归一化后应一次通过，不烧重试。"""
    monkeypatch.setenv("MODEL_ID", "test-model")
    comp_keyed = {f"s{i:02d}": {"value": "yes", "evidence": ""} for i in range(3, 18) if i != 15}
    payload = json.dumps({"title": "t", "one_liner": "o", "facts": FACTS, "features": comp_keyed, "unknowns": []})
    runner = AnthropicRunner(client=_FakeClient([payload]), budget=Budget(max_calls=3))
    data = runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)
    assert set(data["features"]) == set(FEATURE_IDS)
    assert runner.budget.calls == 1


def test_runner_retries_when_features_are_missing(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "test-model")
    bad = json.dumps({"title": "t", "one_liner": "o", "facts": FACTS, "features": {}, "unknowns": []})
    good = json.dumps({"title": "t", "one_liner": "o", "facts": FACTS,
                       "features": {fid: {"value": "no", "evidence": ""} for fid in FEATURE_IDS}, "unknowns": []})
    runner = AnthropicRunner(client=_FakeClient([bad, good]), budget=Budget(max_calls=3))
    data = runner.complete("extract", "sys", "prompt", EXTRACT_SCHEMA)
    assert runner.budget.calls == 2 and data["features"]["scheduled"]["value"] == "no"
