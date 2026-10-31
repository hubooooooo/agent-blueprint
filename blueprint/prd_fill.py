"""把 PRD 第 2–5 节写出来（网页界面用）。

这几节原本由用户的 AI 编程工具按 BLUEPRINT.md 填写；网页用户没有这类工具，PRD 会一直停在模板，
交接包里的 PRD 看起来像半成品。所以网页里每次推导完，根据第 1 节原话、第 6 节回答、第 7 节新需求
和需求拆解的事实，把这四节整理出来。

只覆盖仍是模板、或之前由这里写入（带 MARK）的小节；人或 AI 工具写过的内容一律不动。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from blueprint.knowledge import FACT_KEYS, load_prompt
from blueprint.pipeline import atomic_write
from blueprint.workspace import AUTO_MARK, PRD_NAME, PENDING_HEADING, current_version, read_prd

FILL_STAGE = "chat_prd_fill"
MARK = AUTO_MARK
SECTIONS = [
    ("## 2. 需求拆解", "breakdown"),
    ("## 3. 功能需求", "features"),
    ("## 4. 边界与红线", "boundaries"),
    ("## 5. 成功指标（可度量）", "metrics"),
]
FILL_SCHEMA = {
    "type": "object",
    "required": [key for _h, key in SECTIONS],
    "properties": {key: {"type": "string"} for _h, key in SECTIONS},
}
_FACT_LABEL = {k: v.split("：")[0] for k, v in FACT_KEYS.items()}


def _section_span(text: str, heading: str) -> tuple[int, int] | None:
    """小节正文的起止位置（标题行之后，到下一个 ## 标题之前）。"""
    m = re.search(rf"^{re.escape(heading)}[ \t]*$", text, re.M)        # 不能用 \s*：会吞掉后面的空行
    if not m:
        return None
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return m.end(), (m.end() + nxt.start()) if nxt else len(text)


def _fillable(body: str) -> bool:
    body = body.strip()
    if not body or MARK in body:
        return True
    return bool(re.fullmatch(r"（[^\n]*）", body))          # 模板里的一行占位说明


def fillable_sections(prd: str) -> list[str]:
    out = []
    for heading, key in SECTIONS:
        span = _section_span(prd, heading)
        if span and _fillable(prd[span[0]:span[1]]):
            out.append(key)
    return out


def _mock_fill(prd: str, plan: dict) -> dict:
    facts = plan.get("facts", {})
    rows = ["| 维度 | 内容 | 状态 |", "|---|---|---|"]
    for key, label in _FACT_LABEL.items():
        f = facts.get(key, {})
        rows.append(f"| {label} | {str(f.get('value') or '待确认').replace('|', '／').splitlines()[0]} | {f.get('status', '待确认')} |")
    idea = _section_span(prd, "## 1. 原始需求（逐字保留，不改写）")
    first = ""
    if idea:
        first = next((ln.strip().lstrip("-#* ").strip() for ln in prd[idea[0]:idea[1]].splitlines()
                      if ln.strip() and not ln.strip().startswith("#")), "")
    features = [f"1. FR1（V1）{first or '待确认'}"]
    if PENDING_HEADING in prd:
        for n, (ver, body) in enumerate(re.findall(r"^### (V\d+)（[^）]*）\s*\n+(.+)$", prd.split(PENDING_HEADING, 1)[1], re.M), 2):
            features.append(f"{n}. FR{n}（{ver} 新增）{body.strip()}")
    return {
        "breakdown": "\n".join(rows),
        "features": "\n".join(features),
        "boundaries": f"- {facts.get('boundaries', {}).get('value') or '待确认'}",
        "metrics": f"- 待确认：{facts.get('goal', {}).get('value') or '怎样算做成'}",
    }


def fill_prd(ws: Path, plan: dict, runner, log: Callable[[str], None] = print) -> list[str]:
    """把能写的小节写进 PRD，返回写了哪些。没有可写的小节就不调模型。"""
    ws = Path(ws)
    prd = read_prd(ws)
    keys = fillable_sections(prd)
    if not keys:
        return []
    if getattr(runner, "name", "") == "mock":
        data = _mock_fill(prd, plan)
    else:
        from blueprint.pipeline import StageRunner
        facts = json.dumps(plan.get("facts", {}), ensure_ascii=False, indent=2)
        stages = StageRunner(runner, ws, resume=True, log=log, context={"kind": "prd_fill"})
        data = stages.run(FILL_STAGE, load_prompt(FILL_STAGE).format(prd=prd, facts=facts), FILL_SCHEMA, "⑦ 整理需求文档")
    # 调模型期间 PRD 可能被改过（比如同时保存了回答），重新读一遍再写
    prd = read_prd(ws)
    note = (f"{MARK}\n> 由 Agent 工坊 根据第 1、6、7 节和方案整理（V{current_version(prd)}，{time.strftime('%Y-%m-%d')}）。"
            "要改需求请在界面里加新需求或回答问题，这一节会在下次推导时重新整理。")
    written = []
    for heading, key in SECTIONS:
        span = _section_span(prd, heading)
        content = str(data.get(key) or "").strip()
        if key not in keys or not span or not content or not _fillable(prd[span[0]:span[1]]):
            continue
        prd = prd[:span[0]] + f"\n\n{note}\n\n{content}\n\n" + prd[span[1]:].lstrip("\n")
        written.append(key)
    if written:
        atomic_write(ws / PRD_NAME, prd)
    return written
