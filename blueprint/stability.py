"""加新需求时稳住组件选型：新需求没涉及的特征沿用上一版判断。

需求拆解每次都会把 14 个特征重新判断一遍，模型逐题判断有一两成的波动。升版重推时，和新需求毫不相干的
组件也可能跟着变，页面会把它当成新需求带来的变化，误导用户。所以升版前先判断这条新需求涉及哪些特征
（1 次小调用；离线 mock 用关键词），涉及的照常重新判断，没涉及的沿用上一版。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from blueprint.knowledge import FEATURE_BY_ID, FEATURES, load_prompt

AFFECTED_STAGE = "revise_affected"
AFFECTED_SCHEMA = {
    "type": "object",
    "required": ["affected"],
    "properties": {
        "affected": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
}


def previous_features(ws: Path) -> dict[str, dict]:
    try:
        data = json.loads((Path(ws) / "plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {fid: v for fid, v in (data.get("features") or {}).items() if fid in FEATURE_BY_ID and isinstance(v, dict)}


def affected_features(requirement: str, runner, ws: Path, log: Callable[[str], None] = print) -> set[str]:
    if getattr(runner, "name", "") == "mock":
        from blueprint.mock import _STRONG_KEYWORDS, _WEAK_KEYWORDS
        low = requirement.lower()
        return {fid for fid in FEATURE_BY_ID
                if any(w.lower() in low for w in _STRONG_KEYWORDS.get(fid, []) + _WEAK_KEYWORDS.get(fid, []))}
    from blueprint.pipeline import StageRunner
    features = "\n".join(f"- {f.id}：{f.question}" for f in FEATURES)
    stages = StageRunner(runner, ws, resume=True, log=log, context={"kind": "affected"})
    data = stages.run(AFFECTED_STAGE, load_prompt(AFFECTED_STAGE).format(requirement=requirement, features=features),
                      AFFECTED_SCHEMA, "判断新需求涉及哪些方面")
    return {fid for fid in data.get("affected", []) if fid in FEATURE_BY_ID}


def stable_overrides(requirement: str, ws: Path, runner, old_version: int,
                     log: Callable[[str], None] = print) -> tuple[dict[str, dict], set[str]]:
    """返回（沿用上一版的特征判断, 这次要重新判断的特征）。没有上一版方案时不沿用任何判断。"""
    prev = previous_features(ws)
    if not prev:
        return {}, set(FEATURE_BY_ID)
    affected = affected_features(requirement, runner, ws, log)
    keep = {
        fid: {"value": v.get("value", "unknown"),
              "evidence": f"沿用 V{old_version} 的判断（这次新需求没涉及）：{v.get('evidence', '')}".rstrip("：")}
        for fid, v in prev.items() if fid not in affected
    }
    return keep, affected
