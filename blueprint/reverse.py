"""反向：已有项目 → Agent Harness 差距报告 + 它本该有的 PRD。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from blueprint.agent import supports_agent
from blueprint.forward import _fmt_fact_keys, _fmt_features, _fmt_questions, _dump, vote_on_features
from blueprint.knowledge import ACCEPTANCE, COMPONENT_BY_ID, FACT_KEYS, load_prompt
from blueprint.llm import BudgetExceeded, Runner, cached_note
from blueprint.pipeline import StageRunner
from blueprint.rules import select_components, describe_feature
from blueprint.scanner import Inventory, scan_project
from blueprint.audit_agent import MAX_TURNS, investigate
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
    runner: str = ""                   # 运行器：anthropic（真实调用）或 mock（离线演示）
    model: str = ""                    # 实际用的模型
    budget: dict = field(default_factory=dict)
    mode: str = "fast"                 # agent：模型读代码核实；fast：关键词扫描
    mode_note: str = ""                # 没用上 agent 的原因（--fast、模型不支持、agent 失败）
    basis: str = ""                    # 「应有」组件的来源：plan（方案.md 的选型）、prd、previous 或空（反推）
    agent_stats: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.intent.get("title") or Path(self.root).name

    @property
    def model_label(self) -> str:
        """报告里显示的模型：实际模型名；离线演示或旧结果没有记录时退回运行器名。"""
        return self.model or self.runner

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
            "model": self.model,
            "budget": self.budget,
            "mode": self.mode,
            "mode_note": self.mode_note,
            "basis": self.basis,
            "agent_stats": self.agent_stats,
        }


def compare(decisions: list[dict], inventory: Inventory,
            findings: dict | None = None) -> tuple[list[Gap], float]:
    """findings：agent 核实过的组件结论，优先于扫描器的关键词命中。"""
    gaps: list[Gap] = []
    score = 0.0
    total = 0
    for d in decisions:
        finding = (findings or {}).get(d["id"])
        sig = inventory.components.get(d["id"])
        if finding:
            present = finding["strength"]
            evidence = [f"{e['file']}:{e['line']} {e['note']}" for e in finding["evidence"][:4]]
        elif findings is not None:     # agent 模式：没交结论的组件扫描也没命中（命中的都要求核实了）
            present, evidence = "none", []
        else:
            present = sig.strength if sig else "none"
            evidence = [f"{h.file}:{h.line} `{h.text}`" for h in (sig.hits[:4] if sig else [])]
        verdict, priority = _GAP_MATRIX[(d["decision"], present)]
        comp = COMPONENT_BY_ID[d["id"]]
        gaps.append(Gap(d["id"], d["name"], d["decision"], present, verdict, priority,
                        d["reason"], evidence, comp.readme))
        if d["decision"] == "必选":
            total += 1
            score += _SCORE[present]
    completion = round(score / total, 2) if total else 0.0
    order = {"P0": 0, "P1": 1, "P2": 2, "?": 3, "info": 4, "-": 5}
    gaps.sort(key=lambda g: (order[g.priority], g.id))
    return gaps, completion


def _elements_missing(intent: dict, inventory: Inventory, findings: dict | None = None) -> list[str]:
    """五要素空位：从意图与组件结论（agent 核实过的优先，否则用扫描线索）粗判。"""
    missing: list[str] = []

    def strength(cid: str) -> str:
        if findings is not None:
            return findings.get(cid, {}).get("strength", "none")
        return inventory.components[cid].strength

    if strength("s02") == "none":
        missing.append("工具：没有扫描到任何工具定义（input_schema / tools=[...]）")
    if strength("s07") == "none" and not any("知识" in u or "knowledge" in u.lower()
                                                   for u in intent.get("unknowns", [])):
        missing.append("知识：没有扫描到知识库、技能或检索的痕迹，领域知识从哪来不明")
    if inventory.acceptance.get("observable", {}).get("status") == "fail":
        missing.append("观察：没有日志、指标或轨迹记录，无法确认动作产生了预期效果")
    if not inventory.llm_sdks:
        missing.append("行动：没有扫描到任何模型 SDK 调用，这个项目可能还不是 Agent")
    if strength("s03") == "none":
        missing.append("权限：没有权限检查、路径安全或审批的痕迹，默认全开")
    return missing


AGENT_RESERVE_CALLS = 2        # agent 之后还要留给独立复核的调用次数


def run_audit(project: Path, runner: Runner, out_dir: Path, prd_text: str | None = None,
              resume: bool = False, log: Callable[[str], None] = print, fast: bool = False,
              rejudge: bool = False, expected: list[dict] | None = None) -> tuple[Audit, Path]:
    """fast=True 或模型不支持工具调用时走关键词扫描；否则由 agent 读代码核实，失败自动退回扫描。

    expected：已经定好的选型（产品工作区里 方案.md 的组件选型）。给了就按它对照，不再从 PRD 重新判断特征，
    验收和写骨架时依据的方案才一致；PRD 仍会拆解，用来对照事实。

    没给 PRD、输出目录里有同一项目上次 agent 检查的结果时，特征判断沿用上次的（见 previous_features），
    再次检查的差别只来自代码变化，不来自模型判断的波动；rejudge=True 重新判断。
    """
    project = Path(project).resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{project}")
    log("  ▶ ① 盘点项目（本地扫描，不调模型）")
    inventory = scan_project(project)
    stages = StageRunner(runner, out_dir, resume=resume, log=log,
                         context={"kind": "audit", "inventory": inventory.to_dict(), "prd": prd_text})
    stages.save_json("inventory.json", inventory.to_dict())

    prd_extract = None
    prd_decisions = None
    if prd_text:
        stages.save("prd.md", prd_text)
        prd_extract = stages.run("extract", load_prompt("extract").format(
            fact_keys=_fmt_fact_keys(), features=_fmt_features(),
            questions=_fmt_questions(), input=prd_text), EXTRACT_SCHEMA, "② 拆解对照的 PRD")
        if not fast and expected is None:
            prd_extract["features"] = vote_on_features(prd_extract.get("features", {}), prd_text, stages, log,
                                                       label="② 复核特征判断")
        prd_decisions = [d.to_dict() for d in select_components(prd_extract.get("features", {}))]
    if expected is not None:
        prd_decisions = [dict(d) for d in expected]
    basis = "plan" if expected is not None else ("prd" if prd_text else "")

    intent, findings, agent_stats = None, None, {}
    use_agent, mode_note = _agent_plan(runner, fast)
    carried = None if (prd_text or expected is not None or rejudge or resume) \
        else previous_features(Path(out_dir), project)
    if carried:
        basis = "previous"
        prd_decisions = [d.to_dict() for d in select_components(carried["features"])]
        log(f"  ↻ 特征判断沿用 {carried['date']} 那次检查（要重新判断加 --rejudge）")
    if use_agent:
        log(f"  ▶ {'③' if prd_text else '②'} agent 读代码：反推项目意图、逐个核实组件")
        try:
            intent, findings, agent_stats = investigate(project, inventory, runner, Path(out_dir), prd_decisions,
                                                        log=log, max_turns=_agent_turns(runner), resume=resume,
                                                        basis={"plan": "方案.md 的组件选型", "previous": "上次检查的特征判断"}
                                                        .get(basis, "用户提供的 PRD"))
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 —— agent 失败不能让用户卡住，退回扫描写法
            mode_note = f"agent 未完成（{str(exc)[:160]}），已改用快速扫描"
            log(f"  ⚠ {mode_note}")
    if intent is None:
        intent = stages.run("infer", load_prompt("infer").format(
            fact_keys=_fmt_fact_keys(), features=_fmt_features(),
            readme=inventory.readme or "（没有 README）", tree=inventory.tree,
            inventory_json=_dump(inventory.brief())), EXTRACT_SCHEMA,
            f"{'③' if prd_text else '②'} 反推项目意图（快速扫描）")

    if carried:
        intent = {**intent, "features": carried["features"]}
        agent_stats = {**agent_stats, "features_from": carried["date"]}
    log(f"  ▶ {'④' if prd_text else '③'} 算出它应该有什么（规则），对照打分")
    decisions = prd_decisions or [d.to_dict() for d in select_components(intent.get("features", {}))]
    stages.save_json("stages/select.json", {"components": decisions})
    gaps, completion = compare(decisions, inventory, findings)
    elements_missing = _elements_missing(intent, inventory, findings)

    if findings is not None:
        evidence = {g.id: {"strength": g.present, "evidence": g.evidence[:5]} for g in gaps}
    else:
        evidence = {k: {"strength": v.strength, "hits": [f"{h.file}:{h.line}" for h in v.hits[:5]]}
                    for k, v in inventory.components.items()}
    review = stages.run("audit_review", load_prompt("audit_review").format(
        intent_json=_dump({"title": intent.get("title"), "one_liner": intent.get("one_liner"),
                           "facts": intent.get("facts")}),
        gaps_json=_dump([g.to_dict() for g in gaps if g.priority in ("P0", "P1", "P2")]),
        evidence_json=_dump(evidence)),
        REVIEW_SCHEMA, f"{'⑤' if prd_text else '④'} 独立复核")

    budget = getattr(runner, "budget", None)
    audit = Audit(root=str(project), intent=intent, prd_extract=prd_extract, components=decisions,
                  gaps=gaps, acceptance=inventory.acceptance, elements_missing=elements_missing,
                  completion=completion, review=review, inventory_brief=inventory.brief(),
                  runner=getattr(runner, "name", ""), model=getattr(runner, "model", "") or "",
                  budget=budget.summary() if budget else {},
                  mode="agent" if findings is not None else "fast", mode_note=mode_note,
                  agent_stats=agent_stats, basis=basis)
    stages.save_json("audit.json", audit.to_dict())
    stages.save("本该有的PRD.md", render_should_have_prd(audit))
    doc_path = stages.save("差距报告.md", render_audit(audit))
    return audit, doc_path


def previous_features(out_dir: Path, project: Path) -> dict | None:
    """同一输出目录里上次检查同一项目、由 agent 读代码判断出的特征。快速扫描判断的不沿用（它更容易错）。

    返回 {"features": {...}, "date": "YYYY-MM-DD"}；没有就返回 None。
    """
    path = out_dir / "audit.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    features = (data.get("intent") or {}).get("features")
    if data.get("root") != str(project) or data.get("mode") != "agent" or not isinstance(features, dict):
        return None
    if data.get("prd_extract"):      # 上次是对照 PRD 检查的，特征来自 PRD 而不是代码
        return None
    date = (data.get("agent_stats") or {}).get("features_from") or \
        datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    return {"features": features, "date": date}


def _agent_plan(runner: Runner, fast: bool) -> tuple[bool, str]:
    """要不用 agent，以及不用时写进报告的原因（离线 mock 本来就没有 agent，不写原因）。"""
    if fast:
        return False, "按 --fast 使用快速扫描"
    if os.getenv("BLUEPRINT_AGENT", "").strip().lower() in ("off", "0", "false"):
        return False, "环境变量 BLUEPRINT_AGENT=off，使用快速扫描"
    if not supports_agent(runner):
        return False, "" if getattr(runner, "name", "") == "mock" else "当前模型接入方式不支持工具调用，使用快速扫描"
    if _agent_turns(runner) < 4:
        return False, "费用上限剩余的调用次数太少，使用快速扫描（可调大 --max-calls）"
    return True, ""


def _agent_turns(runner: Runner) -> int:
    budget = getattr(runner, "budget", None)
    if budget is None:
        return MAX_TURNS
    return min(MAX_TURNS, budget.max_calls - budget.calls - AGENT_RESERVE_CALLS)


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
    w(f"> 推导引擎：Agent Blueprint · 模型：{audit.model_label}")
    if audit.mode == "agent":
        w(f"> 本报告由 agent 阅读项目代码得出（读过或搜到 {audit.agent_stats.get('files_seen', 0)} 个文件），未运行被检查项目；"
          "组件现状是 agent 核实代码后的判断，「信号覆盖率」按核实结果计算，不代表生产验收通过。")
    else:
        w("> 本报告基于静态扫描线索，未运行被检查项目；「信号覆盖率」只是静态扫描命中了多少必选组件的关键词信号，不是功能完成度，更不代表生产验收通过。")
        if audit.mode_note:
            w(f"> ⚠️ 本次是快速扫描模式：{audit.mode_note}。组件证据只是关键词命中，可能误报或漏报。")
    if audit.runner == "mock":
        w("> 离线演示：文字与审稿为占位结果，未进行真实模型语义判断。")
        w(">")
        w("> ⚠️ **本报告由 `--mock` 生成，没有调用模型。** 「应有」一列按关键词占位，意图反推多为空白；")
        w("> 配置好 `.env` 后去掉 `--mock` 重新运行，才能得到可用于决策的差距报告。")
    if audit.basis == "plan":
        w("> 对照依据：方案.md 的组件选型（写骨架时依据的同一份方案）；事实对照 PRD")
    elif audit.prd_extract:
        w("> 对照依据：用户提供的 PRD（组件「应有」按 PRD 判定）")
    elif audit.agent_stats.get("features_from"):
        w(f"> 对照依据：沿用 {audit.agent_stats['features_from']} 那次检查的特征判断，这次只重新核实代码；"
          "要重新判断这个项目该有什么，加 `--rejudge`")
    w("")
    w("## 一句话判定")
    w("")
    w(f"**{_grade(audit.completion, sdk_found)}。** 必选组件信号覆盖率 **{pct}%**。")
    w("")
    w("## 它现在是什么")
    w("")
    w(_cell(intent.get("product_summary")) or _cell(intent.get("one_liner")))
    w("")
    facts = intent.get("facts", {})
    prd_facts = (audit.prd_extract or {}).get("facts", {})
    w("| 维度 | 反推结论 | 状态 |")
    w("|---|---|---|")
    for key, label in FACT_KEYS.items():
        f = facts.get(key, {})
        status = f.get("status", "待确认")
        if status == "明确" and audit.prd_extract and prd_facts.get(key, {}).get("status") != "明确":
            status = "按默认假设实现（PRD 待确认）"      # 代码里写死了，不等于需求定了
        w(f"| {label.split('：')[0]} | {_cell(f.get('value')) or '（空）'} | {status} |")
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
        w(f"本次审计消耗：模型调用 {b.get('calls', 0)} 次，输入 {b.get('input_tokens', 0)} tokens，输出 {b.get('output_tokens', 0)} tokens{cached_note(b)}。")
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
