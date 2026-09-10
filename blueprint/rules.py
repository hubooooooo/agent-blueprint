"""组件选型规则：特征 → 组件决策。纯代码，可复现。"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from blueprint.knowledge import COMPONENTS, COMPONENT_BY_ID, FEATURES, FEATURE_BY_ID

DECISIONS = ("必选", "二期", "待确认", "放弃")
_VALUE_TO_DECISION = {"yes": "必选", "later": "二期", "unknown": "待确认", "no": "放弃"}


@dataclass
class ComponentDecision:
    id: str
    name: str
    decision: str
    reason: str
    feature: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def select_components(features: dict[str, dict]) -> list[ComponentDecision]:
    """features: {feature_id: {"value": yes|no|later|unknown, "evidence": str}}"""
    decisions: list[ComponentDecision] = []

    for comp in COMPONENTS:
        if comp.always:
            decisions.append(ComponentDecision(comp.id, comp.name, "必选", comp.when + "（一切基础，恒选）"))

    for feat in FEATURES:
        comp = COMPONENT_BY_ID[feat.component]
        raw = features.get(feat.id) or {}
        value = raw.get("value", "unknown")
        if value not in _VALUE_TO_DECISION:
            value = "unknown"
        evidence = (raw.get("evidence") or "").strip()
        decision = _VALUE_TO_DECISION[value]
        if decision == "待确认":
            reason = f"输入未说明：{feat.question}"
        elif decision == "放弃":
            reason = evidence or f"输入表明不需要：{comp.when}"
        else:
            reason = evidence or comp.when
        decisions.append(ComponentDecision(comp.id, comp.name, decision, reason, feat.id))

    # s15：可选组件里「必选」达到 3 个则必选；含二期达到 3 个则二期
    optional = [d for d in decisions if d.id not in ("s01", "s02", "s15")]
    mvp = [d for d in optional if d.decision == "必选"]
    later = [d for d in optional if d.decision in ("必选", "二期")]
    s15 = COMPONENT_BY_ID["s15"]
    if len(mvp) >= 3:
        d15 = ComponentDecision("s15", s15.name, "必选",
                                f"第一版已选 {len(mvp)} 个可选组件（{', '.join(x.id for x in mvp)}），需归一到单一循环")
    elif len(later) >= 3:
        d15 = ComponentDecision("s15", s15.name, "二期",
                                f"含二期共 {len(later)} 个可选组件，二期集成时需要")
    else:
        d15 = ComponentDecision("s15", s15.name, "放弃", "可选组件不足 3 个，直接在 loop 里挂接即可")
    decisions.append(d15)

    order = {c.id: i for i, c in enumerate(COMPONENTS)}
    decisions.sort(key=lambda d: order[d.id])
    return decisions


def decisions_by_id(decisions: list[ComponentDecision]) -> dict[str, ComponentDecision]:
    return {d.id: d for d in decisions}


def describe_feature(feature_id: str) -> str:
    feat = FEATURE_BY_ID.get(feature_id)
    return feat.question if feat else feature_id
