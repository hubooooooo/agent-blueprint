"""把工作区文件整理成页面要用的数据。只读，不调模型。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from blueprint.knowledge import COMPONENT_BY_ID, FACT_KEYS, FIVE_ELEMENTS, LAYERS
from blueprint.plain import plain_questions
from blueprint.render import architecture_nodes
from blueprint.usage import read_usage
from blueprint.workspace import PRD_NAME, current_version, pending_versions

_FACT_LABEL = {k: v.split("：")[0] for k, v in FACT_KEYS.items()}
_ELEMENT_LABEL = {k: v.split("：")[0] for k, v in FIVE_ELEMENTS.items()}


def resolve_workspace(out_root: Path, slug: str) -> Path:
    """slug 来自网址，只允许指向 out_root 下一层、已有 PRD.md 的工作区。"""
    if not slug or slug.startswith(".") or "/" in slug or "\\" in slug:
        raise LookupError("产品不存在")
    ws = Path(out_root) / slug
    if not (ws / PRD_NAME).is_file():
        raise LookupError("产品不存在")
    return ws


def _product_name(prd_text: str, fallback: str) -> str:
    m = re.search(r"^\|\s*产品名\s*\|\s*(.+?)\s*\|\s*$", prd_text, re.M)
    return m.group(1) if m else fallback


def _load_plan(ws: Path) -> dict | None:
    path = ws / "plan.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def product_summary(ws: Path) -> dict:
    prd = (ws / PRD_NAME).read_text(encoding="utf-8")
    plan = _load_plan(ws)
    mtimes = [p.stat().st_mtime for p in (ws / PRD_NAME, ws / "plan.json") if p.exists()]
    return {
        "slug": ws.name,
        "name": _product_name(prd, ws.name),
        "version": current_version(prd),
        "has_plan": plan is not None,
        "unknowns": len(plain_questions(plan, ws)[0]) if plan else 0,
        "review_ok": bool(plan and plan.get("review", {}).get("ok")),
        "pending_versions": pending_versions(prd),
        "updated": max(mtimes),
    }


def list_products(out_root: Path) -> list[dict]:
    out_root = Path(out_root)
    if not out_root.is_dir():
        return []
    spaces = [p.parent for p in out_root.glob(f"*/{PRD_NAME}") if not p.parent.name.startswith(".")]
    return sorted((product_summary(ws) for ws in spaces), key=lambda s: s["updated"], reverse=True)


def plan_view(plan: dict, ws: Path | None = None) -> dict:
    """待确认清单与 方案.md 同口径（需求未知项 + 设计开放问题 + 待确认组件），但这里用大白话版本，
    并把只有工程师能判断的技术备注分到 dev_items（见 blueprint/plain.py）。"""
    design = plan.get("design", {})
    questions, dev_items = plain_questions(plan, ws)
    facts = plan.get("facts", {})
    components = []
    for c in plan.get("components", []):
        meta = COMPONENT_BY_ID.get(c["id"])
        components.append({**c, "domain": meta.domain if meta else "", "one_liner": meta.one_liner if meta else "",
                           "when": meta.when if meta else ""})
    tool_list = design.get("tool_list", [])
    nodes = architecture_nodes(plan.get("components", []), tool_list, design.get("tech_stack_and_deployment", ""))
    layers = [{"num": num, "name": name, "question": q, "detail": detail}
              for (num, name, q, _anchor), (_label, detail) in zip(LAYERS, nodes)]
    return {
        "title": plan.get("title", ""),
        "one_liner": plan.get("one_liner", ""),
        "runner": plan.get("runner", ""),
        "unknowns": [q["text"] for q in questions],
        "questions": questions,
        "dev_items": dev_items,
        "facts": [{"key": k, "label": label, "value": facts.get(k, {}).get("value", ""),
                   "status": facts.get(k, {}).get("status", "待确认")} for k, label in _FACT_LABEL.items()],
        "elements": [{"key": k, "label": label, "items": plan.get("elements", {}).get(k, [])}
                     for k, label in _ELEMENT_LABEL.items()],
        "components": components,
        "layers": layers,
        "tool_list": tool_list,
        "system_prompt": design.get("system_prompt", ""),
        "context_memory_strategy": design.get("context_memory_strategy", ""),
        "security_and_degradation": design.get("security_and_degradation", []),
        "observability": design.get("observability", {}),
        "tech_stack_and_deployment": design.get("tech_stack_and_deployment", ""),
        "review": plan.get("review", {}),
        "design_attempts": plan.get("design_attempts", 1),
        "budget": plan.get("budget", {}),
    }


def product_detail(ws: Path) -> dict:
    plan = _load_plan(ws)
    return {**product_summary(ws), "path": str(ws.resolve()), "plan": plan_view(plan, ws) if plan else None,
            "usage": read_usage(ws)}
