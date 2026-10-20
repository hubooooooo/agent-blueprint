"""mock 启发式必须偏向「宁可少选」：弱信号只能落到待确认，不能把题库里该放弃的组件选成必选。"""
import json
from pathlib import Path

import pytest

from blueprint.mock import _guess_features
from blueprint.rules import select_components

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted(p for p in (ROOT / "evals/forward").iterdir() if (p / "input.md").exists())


def _decisions(text: str) -> dict:
    return {d.id: d.decision for d in select_components(_guess_features(text))}


def test_single_weak_signal_is_pending_not_yes():
    feats = _guess_features("客服团队每天收到很多工单")
    assert feats["parallel_isolated"]["value"] == "unknown"      # 「团队」只是弱信号
    assert feats["scheduled"]["value"] == "yes"                   # 「每天」是强信号


def test_two_weak_signals_add_up():
    feats = _guess_features("一篇 30 页论文要读很久")
    assert feats["context_heavy"]["value"] == "yes"


def test_later_marker_still_detected_on_strong_hit():
    feats = _guess_features("未来希望记住孩子的偏好")
    assert feats["cross_session_memory"]["value"] == "later"


def test_destructive_verbs_remain_strong():
    assert _guess_features("可以执行删除文件、重启服务")["destructive_ops"]["value"] == "yes"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_mock_never_selects_components_the_answer_key_drops(case: Path):
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))["components"]
    got = _decisions((case / "input.md").read_text(encoding="utf-8"))
    overshoot = {cid: got[cid] for cid, want in expected.items()
                 if want == "放弃" and got.get(cid) in ("必选", "二期")}
    assert not overshoot, f"{case.name}: 标准答案放弃但 mock 选上了 {overshoot}"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_mock_keeps_the_clear_must_haves(case: Path):
    """强信号明确的必选项（s03 权限、s07 知识）mock 也应该能选上，证明不是一刀切全判待确认。"""
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))["components"]
    got = _decisions((case / "input.md").read_text(encoding="utf-8"))
    for cid in ("s03", "s07"):
        if expected.get(cid) == "必选":
            assert got[cid] == "必选", f"{case.name}: {cid} 应为必选，mock 判 {got[cid]}"


def test_later_is_judged_per_clause_not_per_sentence():
    now_and_later = _guess_features("现在就要记住用户偏好，未来再做个性化推荐。")
    assert now_and_later["cross_session_memory"]["value"] == "yes"
    only_later = _guess_features("未来希望记住孩子的年龄和偏好玩具做个性化，未来也希望自动判断剧情算不算合格。")
    assert only_later["cross_session_memory"]["value"] == "later"
    assert only_later["auto_completion"]["value"] == "later"
    assert _guess_features("记住偏好、个性化（二期）")["cross_session_memory"]["value"] == "later"

