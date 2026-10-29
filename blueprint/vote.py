"""特征判断取多数票：同一份材料另外独立判断两次特征，三票取多数。

同一份输入，模型逐题判断特征每次会有一两题不一样（实测引擎检查自己 5 次，14 个特征里 3 个有分歧，
每个都是 4 比 1）。选型完全由特征决定，所以一题翻转就会让一个组件在必选和放弃之间跳。多数票把单次的偶然
判断压下去：只多两次小调用（只判断特征，不重做事实和问题清单）。三票各不相同时判 unknown，进待确认。
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Callable

from blueprint.knowledge import load_prompt
from blueprint.schema import EXTRACT_SCHEMA, FEATURE_IDS

VOTE_STAGES = ("vote_features_1", "vote_features_2")
VOTE_SCHEMA = {"type": "object", "required": ["features"],
               "properties": {"features": EXTRACT_SCHEMA["properties"]["features"]}}
MIN_CALLS_LEFT = 8          # 投票后至少还要留这么多次调用给后面的步骤，否则不投


def enabled(runner) -> bool:
    """离线 mock、BLUEPRINT_VOTE=off、剩余调用次数不够时不投票。"""
    if getattr(runner, "name", "") == "mock":
        return False
    if os.getenv("BLUEPRINT_VOTE", "").strip().lower() in ("off", "0", "false"):
        return False
    budget = getattr(runner, "budget", None)
    return budget is None or budget.max_calls - budget.calls >= len(VOTE_STAGES) + MIN_CALLS_LEFT


def feature_prompt(material: str) -> str:
    """特征问题这一节直接从 extract.md 截取，两处口径不会改歧。"""
    from blueprint.forward import _fmt_features
    extract = load_prompt("extract")
    rules = extract[extract.index("## 特征问题"):extract.index("## 待确认清单")].strip()
    return load_prompt("vote_features").replace("@@特征问题@@", rules).format(features=_fmt_features(), input=material)


def cast(material: str, complete: Callable[[str, str, dict], dict]) -> list[dict]:
    """另外两次独立判断。complete(stage, prompt, schema) 由调用方决定走缓存还是直接调模型。"""
    prompt = feature_prompt(material)
    return [complete(stage, prompt, VOTE_SCHEMA)["features"] for stage in VOTE_STAGES]


def majority(first: dict, others: list[dict]) -> tuple[dict, list[str]]:
    """first 是原判断，others 是另外几次。返回 (投票后的特征, 改判说明)。

    得票过半的取值胜出，依据沿用第一张投这个值的票（原判断优先）；没有过半的判 unknown。
    """
    voted: dict[str, dict] = {}
    changes: list[str] = []
    for fid in FEATURE_IDS:
        ballots = [b.get(fid) if isinstance(b.get(fid), dict) else {"value": "unknown"} for b in [first, *others]]
        values = [str(b.get("value", "unknown")) for b in ballots]
        top, count = Counter(values).most_common(1)[0]
        tally = " / ".join(values)
        if count * 2 > len(values):
            pick = next(b for b in ballots if b.get("value") == top)
        else:
            pick = {"value": "unknown", "evidence": f"几次判断各不相同（{tally}），先列为待确认"}
        voted[fid] = {"value": pick["value"], "evidence": str(pick.get("evidence", ""))}
        if pick["value"] != values[0]:
            changes.append(f"{fid}：{values[0]} → {pick['value']}（{tally}）")
    return voted, changes
