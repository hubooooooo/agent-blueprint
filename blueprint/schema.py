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
        "features": {"type": "object", "additionalProperties": _FEATURE},
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
                 "security_and_degradation", "observability", "tech_stack_and_deployment"],
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
