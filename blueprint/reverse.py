"""反向：已有项目 → Agent Harness 差距报告 + 它本该有的 PRD。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from blueprint.forward import _fmt_fact_keys, _fmt_features, _fmt_questions, _dump
from blueprint.knowledge import ACCEPTANCE, COMPONENT_BY_ID, FACT_KEYS, load_prompt
from blueprint.llm import Runner
from blueprint.pipeline import StageRunner
from blueprint.rules import select_components, describe_feature
from blueprint.scanner import Inventory, scan_project
from blueprint.schema import EXTRACT_SCHEMA, REVIEW_SCHEMA

# 期望 × 现状 → 差距判定
#   期望：必选 / 二期 / 待确认 / 放弃
#   现状：strong / weak / none
_GAP_MATRIX = {
    ("必选", "none"): ("缺失", "P0"),
    ("必选", "weak"): ("薄弱", "P1"),
    ("必选", "strong"): ("已具备", "-"),
    ("二期", "none"): ("二期补齐", "P2"),
    ("二期", "weak"): ("二期加固", "P2"),
    ("二期", "strong"): ("已具备", "-"),
    ("待确认", "none"): ("待确认", "?"),
    ("待确认", "weak"): ("已有雏形，需确认是否要", "?"),
    ("待确认", "strong"): ("已具备，需确认是否要", "?"),
    ("放弃", "none"): ("不需要", "-"),
    ("放弃", "weak"): ("可能多余", "info"),
    ("放弃", "strong"): ("可能多余", "info"),
}
_SCORE = {"strong": 1.0, "weak": 0.5, "none": 0.0}


@dataclass
class Gap:
    id: str
    name: str
    expected: str
    present: str
    verdict: str
    priority: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    readme: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Audit:
    root: str
    intent: dict
    prd_extract: dict | None
    components: list[dict]
    gaps: list[Gap]
    acceptance: dict
    elements_missing: list[str]
    completion: float
    review: dict
    inventory_brief: dict
    runner: str = ""
    budget: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.intent.get("title") or Path(self.root).name

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "title": self.title,
            "intent": self.intent,
            "prd_extract": self.prd_extract,
            "components": self.components,
            "gaps": [g.to_dict() for g in self.gaps],
            "acceptance": self.acceptance,
            "elements_missing": self.elements_missing,
            "completion": self.completion,
            "review": self.review,
            "inventory": self.inventory_brief,
            "runner": self.runner,
            "budget": self.budget,
        }


def compare(decisions: list[dict], inventory: Inventory) -> tuple[list[Gap], float]:
    gaps: list[Gap] = []
    score = 0.0
    total = 0
    for d in decisions:
        sig = inventory.components.get(d["id"])
        present = sig.strength if sig else "none"
        verdict, priority = _GAP_MATRIX[(d["decision"], present)]
        comp = COMPONENT_BY_ID[d["id"]]
        evidence = [f"{h.file}:{h.line} `{h.text}`" for h in (sig.hits[:4] if sig else [])]
        gaps.append(Gap(d["id"], d["name"], d["decision"], present, verdict, priority,
                        d["reason"], evidence, comp.readme))
        if d["decision"] == "必选":
            total += 1
            score += _SCORE[present]
    completion = round(score / total, 2) if total else 0.0
    order = {"P0": 0, "P1": 1, "P2": 2, "?": 3, "info": 4, "-": 5}
    gaps.sort(key=lambda g: (order[g.priority], g.id))
    return gaps, completion


def _elements_missing(intent: dict, inventory: Inventory) -> list[str]:
    """五要素空位：从意图与扫描线索粗判。"""
    missing: list[str] = []
    comps = inventory.components
    if comps["s02"].strength == "none":
        missing.append("工具：没有扫描到任何工具定义（input_schema / tools=[...]）")
    if comps["s07"].strength == "none" and not any("知识" in u or "knowledge" in u.lower()
                                                   for u in intent.get("unknowns", [])):
        missing.append("知识：没有扫描到知识库、技能或检索的痕迹，领域知识从哪来不明")
    if inventory.acceptance.get("observable", {}).get("status") == "fail":
        missing.append("观察：没有日志、指标或轨迹记录，无法确认动作产生了预期效果")
    if not inventory.llm_sdks:
        missing.append("行动：没有扫描到任何模型 SDK 调用，这个项目可能还不是 Agent")
    if comps["s03"].strength == "none":
        missing.append("权限：没有权限检查、路径安全或审批的痕迹，默认全开")
    return missing


def run_audit(project: Path, runner: Runner, out_dir: Path, prd_text: str | None = None,
              resume: bool = False, log: Callable[[str], None] = print) -> tuple[Audit, Path]:
    project = Path(project).resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{project}")
    log("  ▶ ① 盘点项目（本地扫描，不调模型）")
    inventory = scan_project(project)
    stages = StageRunner(runner, out_dir, resume=resume, log=log,
                         context={"kind": "audit", "inventory": inventory.to_dict(), "prd": prd_text})
    stages.save_json("inventory.json", inventory.to_dict())

    intent = stages.run("infer", load_prompt("infer").format(
        fact_keys=_fmt_fact_keys(), features=_fmt_features(),
        readme=inventory.readme or "（没有 README）", tree=inventory.tree,
        inventory_json=_dump(inventory.brief())), EXTRACT_SCHEMA, "② 反推项目意图")

    prd_extract = None
    features = intent.get("features", {})
    if prd_text:
        stages.save("prd.md", prd_text)
        prd_extract = stages.run("extract", load_prompt("extract").format(
            fact_keys=_fmt_fact_keys(), features=_fmt_features(),
            questions=_fmt_questions(), input=prd_text), EXTRACT_SCHEMA, "②' 拆解对照 PRD")
        features = prd_extract.get("features", {})

    log("  ▶ ③ 算出它应该有什么（规则）")
    decisions = [d.to_dict() for d in select_components(features)]
    stages.save_json("stages/select.json", {"components": decisions})

    log("  ▶ ④ 对照打分")
    gaps, completion = compare(decisions, inventory)
    elements_missing = _elements_missing(intent, inventory)

    review = stages.run("audit_review", load_prompt("audit_review").format(
        intent_json=_dump({"title": intent.get("title"), "one_liner": intent.get("one_liner"),
                           "facts": intent.get("facts")}),
        gaps_json=_dump([g.to_dict() for g in gaps if g.priority in ("P0", "P1", "P2")]),
        evidence_json=_dump({k: {"strength": v.strength, "hits": [f"{h.file}:{h.line}" for h in v.hits[:5]]}
                             for k, v in inventory.components.items()})),
        REVIEW_SCHEMA, "⑤ 独立复核")

    budget = getattr(runner, "budget", None)
    audit = Audit(root=str(project), intent=intent, prd_extract=prd_extract, components=decisions,
                  gaps=gaps, acceptance=inventory.acceptance, elements_missing=elements_missing,
                  completion=completion, review=review, inventory_brief=inventory.brief(),
                  runner=getattr(runner, "name", ""), budget=budget.summary() if budget else {})
    stages.save_json("audit.json", audit.to_dict())
    stages.save("本该有的PRD.md", render_should_have_prd(audit))
    doc_path = stages.save("差距报告.md", render_audit(audit))
    return audit, doc_path


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _cell(text) -> str:
    return str(text or "").replace("|", "／").replace("\n", " ").strip()


def _grade(completion: float, sdk_found: bool) -> str:
    if not sdk_found:
        return "还不是 Agent：没有扫描到模型调用"
    if completion >= 0.9:
        return "接近完整的 Agent Harness"
    if completion >= 0.6:
        return "有骨架，缺关键机制"
    if completion >= 0.3:
        return "只有雏形"
    return "离 Agent Harness 还很远"


def render_audit(audit: Audit) -> str:
    out: list[str] = []
    w = out.append
    intent = audit.intent
    sdk_found = bool(audit.inventory_brief.get("llm_sdks"))
    pct = int(audit.completion * 100)

    w(f"# Agent Harness 差距报告 ——「{audit.title}」")
    w("")
    w(f"> 项目路径：`{audit.root}`")
    w(f"> 推导引擎：Agent Blueprint · 模型：{audit.runner}")
    w("> 本报告基于静态扫描线索，未运行被检查项目；完成度是组件信号覆盖率，不代表生产验收通过。")
    if audit.runner == "mock":
        w("> 离线演示：文字与审稿为占位结果，未进行真实模型语义判断。")
    if audit.prd_extract:
        w("> 对照依据：用户提供的 PRD（组件「应有」按 PRD 判定）")
    w("")
    w("## 一句话判定")
    w("")
    w(f"**{_grade(audit.completion, sdk_found)}。** 必选组件完成度 **{pct}%**。")
    w("")
    w("## 它现在是什么")
    w("")
    w(_cell(intent.get("product_summary")) or _cell(intent.get("one_liner")))
    w("")
    facts = intent.get("facts", {})
    w("| 维度 | 反推结论 | 状态 |")
    w("|---|---|---|")
    for key, label in FACT_KEYS.items():
        f = facts.get(key, {})
        w(f"| {label.split('：')[0]} | {_cell(f.get('value')) or '（空）'} | {f.get('status', '待确认')} |")
    w("")

    w("## 组件差距表（按优先级）")
    w("")
    w("| 优先级 | 组件 | 应有 | 现状 | 判定 | 为什么这类产品需要它 | 去哪看 |")
    w("|---|---|---|---|---|---|---|")
    present_mark = {"strong": "✅ 有", "weak": "🟡 弱", "none": "❌ 无"}
    for g in audit.gaps:
        w(f"| {g.priority} | {g.id} {g.name} | {g.expected} | {present_mark[g.present]} | {g.verdict} | {_cell(g.reason)} | {g.readme} |")
    w("")

    w("## 五要素空位")
    w("")
    if audit.elements_missing:
        for m in audit.elements_missing:
            w(f"- {m}")
    else:
        w("五要素都能在项目里找到对应痕迹。")
    w("")

    w("## 六条验收标准")
    w("")
    w("| 标准 | 要求 | 结果 | 证据 |")
    w("|---|---|---|---|")
    mark = {"pass": "✅ 通过", "partial": "🟡 部分", "fail": "❌ 不过"}
    for key, (name, desc) in ACCEPTANCE.items():
        a = audit.acceptance.get(key, {})
        w(f"| {name} | {desc} | {mark.get(a.get('status'), '?')} | {_cell('、'.join(a.get('evidence', [])[:3]))} |")
    w("")

    w("## 建议下一步（按顺序做）")
    w("")
    n = 0
    for g in audit.gaps:
        if g.priority in ("P0", "P1"):
            n += 1
            comp = COMPONENT_BY_ID[g.id]
            w(f"{n}. **{g.verdict}：{g.id} {g.name}** —— {comp.one_liner}。生产级要点：{comp.production_points}。参考 `{comp.readme}`。")
    for key, (name, _desc) in ACCEPTANCE.items():
        if audit.acceptance.get(key, {}).get("status") == "fail":
            n += 1
            w(f"{n}. **补齐验收：{name}** —— {ACCEPTANCE[key][1]}。")
    if n == 0:
        w("没有 P0 / P1 差距。可以对照「二期」项和待确认项继续演进。")
    w("")

    pending = [g for g in audit.gaps if g.priority == "?"]
    unknowns = intent.get("unknowns", [])
    if pending or unknowns:
        w("## 需要项目作者回答的问题")
        w("")
        k = 0
        for u in unknowns:
            k += 1
            w(f"{k}. {u}")
        for g in pending:
            k += 1
            feature = next((d.get("feature", "") for d in audit.components if d["id"] == g.id), "")
            w(f"{k}. 【{g.id} {g.name}】{describe_feature(feature)}（现状：{present_mark[g.present]}）")
        w("")

    w("## 独立复核意见")
    w("")
    r = audit.review
    w(f"- 结论：{'✅ 复核通过' if r.get('ok') else '❌ 复核有异议'}")
    w(f"- 总评：{_cell(r.get('summary'))}")
    for i in r.get("issues", []):
        w(f"- [{i.get('severity', '')}] {i.get('component', '')}：{_cell(i.get('problem'))}")
    w("")

    w("## 证据附录")
    w("")
    for g in audit.gaps:
        if g.evidence:
            w(f"- **{g.id} {g.name}**：" + "；".join(g.evidence[:3]))
    sdks = audit.inventory_brief.get("llm_sdks", {})
    if sdks:
        w("- **模型 SDK**：" + "；".join(f"{k}（{', '.join(v)}）" for k, v in sdks.items()))
    w("")
    if audit.budget:
        b = audit.budget
        w(f"本次审计消耗：模型调用 {b.get('calls', 0)} 次，输入 {b.get('input_tokens', 0)} tokens，输出 {b.get('output_tokens', 0)} tokens。")
        w("")
    w("附：`本该有的PRD.md` 可以直接喂给 `blueprint plan` 生成完整方案。")
    w("")
    return "\n".join(out)


def render_should_have_prd(audit: Audit) -> str:
    intent = audit.prd_extract or audit.intent
    facts = intent.get("facts", {})
    out = [f"# {audit.title}", "", f"> {intent.get('one_liner', '')}", "",
           "本文档由 Agent Blueprint 反向推导生成：这是该项目「本该有」的需求描述。请核对并补全「待确认」项，然后交给 `blueprint plan`。", ""]
    for key, label in FACT_KEYS.items():
        f = facts.get(key, {})
        out.append(f"## {label.split('：')[0]}")
        out.append("")
        out.append((_cell(f.get("value")) or "（待确认）") + ("" if f.get("status") == "明确" else "  ⚠️ 待确认"))
        out.append("")
    unknowns = intent.get("unknowns", [])
    if unknowns:
        out.append("## 待确认")
        out.append("")
        out += [f"- {u}" for u in unknowns]
        out.append("")
    return "\n".join(out)
