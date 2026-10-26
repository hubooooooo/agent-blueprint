"""待确认问题的大白话版本（blueprint/plain.py）：组件问题手写版不漏、模型改写的缓存与回退、分流。"""
import json

from blueprint.knowledge import FEATURES
from blueprint.mock import MockRunner
from blueprint.plain import FEATURE_PLAIN, PLAIN_STAGE, plain_questions, rewrite_questions

PLAN = {
    "unknowns": ["目标孩子的年龄段是多少？", "交互形态是小程序、App 还是网页？"],
    "design": {"open_questions": ["组件 s03 特征标为 destructive_ops，建议同步修正标签"]},
    "components": [
        {"id": "s01", "name": "Agent Loop", "decision": "必选", "feature": ""},
        {"id": "s12", "name": "定时调度", "decision": "待确认", "feature": "scheduled"},
    ],
}


def test_every_feature_has_a_plain_question_without_jargon():
    assert set(FEATURE_PLAIN) == {f.id for f in FEATURES}
    for fid, text in FEATURE_PLAIN.items():
        assert text.endswith(("？", "。")), fid
        for jargon in ("上下文", "MCP", "Agent", "持久化", "审计", "埋点", "评估器"):
            assert jargon not in text, (fid, jargon)


def test_without_rewrites_falls_back_to_original_and_plain_component_questions(tmp_path):
    users, devs = plain_questions(PLAN, tmp_path)
    assert [q["text"] for q in users[:3]] == PLAN["unknowns"] + PLAN["design"]["open_questions"]
    assert devs == []
    comp = users[-1]
    assert comp["text"].startswith(FEATURE_PLAIN["scheduled"]) and comp["text"].endswith("（关系到组件 s12 定时调度）")
    assert comp["original"].startswith("【组件 s12 定时调度】") and comp["component"] == "s12"


def test_mock_rewrite_routes_technical_notes_to_developers(tmp_path):
    rewrite_questions(PLAN, MockRunner(), tmp_path, log=lambda _m: None)
    users, devs = plain_questions(PLAN, tmp_path)
    assert [q["original"] for q in devs] == PLAN["design"]["open_questions"]
    assert [q["text"] for q in users][:2] == PLAN["unknowns"]


def test_model_rewrites_are_applied_by_index(tmp_path):
    stages = tmp_path / "stages"
    stages.mkdir()
    (stages / f"{PLAIN_STAGE}.source.json").write_text(json.dumps(PLAN["unknowns"], ensure_ascii=False), encoding="utf-8")
    (stages / f"{PLAIN_STAGE}.json").write_text(json.dumps({"items": [
        {"index": 1, "plain": "做成手机小程序、App 还是网页？", "audience": "user"},
        {"index": 0, "plain": "孩子大概几岁？", "audience": "user"},
        {"index": 9, "plain": "越界的编号要忽略", "audience": "user"},
    ]}, ensure_ascii=False), encoding="utf-8")
    users, _ = plain_questions(PLAN, tmp_path)
    assert [q["text"] for q in users[:2]] == ["孩子大概几岁？", "做成手机小程序、App 还是网页？"]
    assert users[0]["original"] == "目标孩子的年龄段是多少？"


def test_stale_rewrites_never_attach_to_new_questions(tmp_path):
    rewrite_questions(PLAN, MockRunner(), tmp_path, log=lambda _m: None)
    changed = {**PLAN, "unknowns": ["一个全新的问题？"], "design": {"open_questions": []}}
    users, devs = plain_questions(changed, tmp_path)
    assert users[0] == {"text": "一个全新的问题？", "original": "一个全新的问题？"} and devs == []


def test_failed_rewrite_keeps_previous_pair_consistent(tmp_path):
    rewrite_questions(PLAN, MockRunner(), tmp_path, log=lambda _m: None)

    class Broken:
        name = "anthropic"

        def complete(self, *a, **k):
            raise RuntimeError("网络断了")

    changed = {**PLAN, "unknowns": ["新问题 A？"] + PLAN["unknowns"]}
    try:
        rewrite_questions(changed, Broken(), tmp_path, log=lambda _m: None)
    except RuntimeError:
        pass
    users, devs = plain_questions(changed, tmp_path)
    assert users[0]["text"] == "新问题 A？"                     # 新问题没有改写，就用原文
    assert [q["original"] for q in devs] == PLAN["design"]["open_questions"]   # 旧的配对仍按原文匹配，没错位


def _write(ws, questions, items):
    stages = ws / "stages"
    stages.mkdir(exist_ok=True)
    (stages / f"{PLAIN_STAGE}.source.json").write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    (stages / f"{PLAIN_STAGE}.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


def test_duplicates_are_asked_once_and_remember_merged_originals(tmp_path):
    qs = ["面包清单从哪来？", "红线有哪些？", "今日面包清单的载体与格式？"]
    plan = {"unknowns": qs[:2], "design": {"open_questions": qs[2:]}, "components": []}
    _write(tmp_path, qs, [
        {"index": 0, "plain": "面包清单你打算怎么更新？", "audience": "user"},
        {"index": 1, "plain": "哪些事必须你点头？", "audience": "user"},
        {"index": 2, "plain": "同上", "audience": "user", "duplicate_of": 0},
    ])
    users, devs = plain_questions(plan, tmp_path)
    assert [q["text"] for q in users] == ["面包清单你打算怎么更新？", "哪些事必须你点头？"]
    assert users[0]["merged"] == ["今日面包清单的载体与格式？"] and devs == []


def test_bad_duplicate_pointers_are_ignored(tmp_path):
    qs = ["甲？", "乙？"]
    plan = {"unknowns": qs, "design": {}, "components": []}
    _write(tmp_path, qs, [
        {"index": 0, "plain": "甲", "audience": "user", "duplicate_of": 1},   # 指向后面：不认
        {"index": 1, "plain": "乙", "audience": "user", "duplicate_of": 1},   # 指向自己：不认
    ])
    assert [q["text"] for q in plain_questions(plan, tmp_path)[0]] == ["甲", "乙"]
    # 被指向的那条已经不在当前问题里：不并，免得把问题弄丢
    plan2 = {"unknowns": ["乙？"], "design": {}, "components": []}
    _write(tmp_path, qs, [{"index": 1, "plain": "乙", "audience": "user", "duplicate_of": 0}])
    assert [q["text"] for q in plain_questions(plan2, tmp_path)[0]] == ["乙"]
