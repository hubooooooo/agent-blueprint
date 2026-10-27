"""迷你 JSON Schema 校验器：object / array / string / number / integer / boolean / enum / required。

只覆盖引擎自己用到的子集，不依赖第三方库。
"""

from __future__ import annotations

from typing import Any


def validate(schema: dict, data: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    _check(schema, data, path, errors)
    return errors


def _check(schema: dict, data: Any, path: str, errors: list[str]) -> None:
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: 期望 {schema['enum']} 之一，实际 {data!r}")
        return
    typ = schema.get("type")
    if typ is None:
        return
    types = typ if isinstance(typ, list) else [typ]
    if not any(_is_type(data, t) for t in types):
        errors.append(f"{path}: 期望类型 {typ}，实际 {type(data).__name__}")
        return
    if "object" in types and isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: 缺少必填字段 {key}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in data:
                _check(sub, data[key], f"{path}.{key}", errors)
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for key, value in data.items():
                if key not in props:
                    _check(extra, value, f"{path}.{key}", errors)
        elif extra is False:
            for key in data:
                if key not in props:
                    errors.append(f"{path}: 不允许的字段 {key}")
    if "array" in types and isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: 至少 {schema['minItems']} 项，实际 {len(data)}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: 至多 {schema['maxItems']} 项，实际 {len(data)}")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(data):
                _check(items, item, f"{path}[{i}]", errors)
    if "string" in types and isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: 长度至少 {schema['minLength']}")
    if ("integer" in types or "number" in types) and isinstance(data, (int, float)):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: 不能小于 {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: 不能大于 {schema['maximum']}")


def _is_type(data: Any, t: str) -> bool:
    if t == "object":
        return isinstance(data, dict)
    if t == "array":
        return isinstance(data, list)
    if t == "string":
        return isinstance(data, str)
    if t == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if t == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if t == "boolean":
        return isinstance(data, bool)
    if t == "null":
        return data is None
    return False


# ---------------------------------------------------------------------------
# 各阶段的输出 schema
# ---------------------------------------------------------------------------

_FACT = {
    "type": "object",
    "required": ["value", "status"],
    "properties": {
        "value": {"type": "string"},
        "status": {"type": "string", "enum": ["明确", "待确认"]},
        "source": {"type": "string"},
    },
}

_FEATURE = {
    "type": "object",
    "required": ["value"],
    "properties": {
        "value": {"type": "string", "enum": ["yes", "no", "later", "unknown"]},
        "evidence": {"type": "string"},
    },
}

FACT_IDS = ["goal", "users", "core_loop", "deliverable", "boundaries", "constraints"]

# 14 个特征 id 是选型规则的输入，缺一个就会被当成 unknown，所以必须作为必填键校验。
from blueprint.knowledge import FEATURES as _FEATURES  # noqa: E402

FEATURE_IDS = [f.id for f in _FEATURES]
_COMPONENT_TO_FEATURE = {f.component: f.id for f in _FEATURES}
_FEATURE_VALUES = ("yes", "no", "later", "unknown")


def coerce_stage_output(stage: str, data: Any) -> Any:
    """在 schema 校验之前，把模型输出里「结构对、写法偏」的地方拉回标准形态。

    目前只处理 features 块（extract / infer 阶段）：
    - 键写成组件编号（s03）而不是特征 id（destructive_ops）→ 按映射表改回来；
      真实模型跑题库时出现过这种输出，当时所有特征都被当成 unknown，整份方案全部「待确认」。
    - 值写成裸字符串（"yes"）而不是对象 → 包成 {"value": "yes", "evidence": ""}。
    - 既不是特征 id 也不是组件编号的键 → 丢弃，避免多余字段触发校验失败。
    不补缺失的键：缺键交给 required 校验去触发一次纠错重试，让模型自己补。
    """
    base = stage.removesuffix("_retry")
    if base not in ("extract", "infer") or not isinstance(data, dict):
        return data
    features = data.get("features")
    if not isinstance(features, dict):
        return data
    fixed: dict[str, Any] = {}
    for key, value in features.items():
        k = str(key).strip()
        fid = k if k in FEATURE_IDS else _COMPONENT_TO_FEATURE.get(k.lower())
        if fid is None:
            continue
        if isinstance(value, str):
            value = {"value": value.strip().lower(), "evidence": ""}
        if fid not in fixed:            # 标准键优先，不被别名覆盖
            fixed[fid] = value
    data = dict(data)
    data["features"] = fixed
    return data

EXTRACT_SCHEMA = {
    "type": "object",
    "required": ["title", "one_liner", "facts", "features", "unknowns"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "one_liner": {"type": "string"},
        "product_summary": {"type": "string"},
        "facts": {
            "type": "object",
            "required": FACT_IDS,
            "properties": {k: _FACT for k in FACT_IDS},
        },
        "features": {"type": "object", "required": FEATURE_IDS, "additionalProperties": _FEATURE},
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
}

_STR_LIST = {"type": "array", "items": {"type": "string"}}

MODEL_SCHEMA = {
    "type": "object",
    "required": ["tools", "knowledge", "observation", "action", "permissions"],
    "properties": {k: _STR_LIST for k in ["tools", "knowledge", "observation", "action", "permissions"]},
}

DESIGN_SCHEMA = {
    "type": "object",
    "required": ["tool_list", "system_prompt", "context_memory_strategy",
                 "security_and_degradation", "observability", "tech_stack_and_deployment", "testing"],
    "properties": {
        "tool_list": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "input", "output", "side_effect", "permission", "layer"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "side_effect": {"type": "string"},
                    "permission": {"type": "string", "enum": ["allow", "ask", "deny"]},
                    "layer": {"type": "string"},
                },
            },
        },
        "system_prompt": {"type": "string", "minLength": 20},
        "context_memory_strategy": {"type": "string"},
        "security_and_degradation": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "observability": {
            "type": "object",
            "required": ["logs", "metrics", "trajectory"],
            "properties": {"logs": _STR_LIST, "metrics": _STR_LIST, "trajectory": {"type": "string"}},
        },
        "tech_stack_and_deployment": {"type": "string"},
        "testing": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "open_questions": _STR_LIST,
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["ok", "issues", "summary"],
    "properties": {
        "ok": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["problem", "severity"],
                "properties": {
                    "section": {"type": "string"},
                    "component": {"type": "string"},
                    "problem": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                },
            },
        },
        "summary": {"type": "string"},
    },
}
