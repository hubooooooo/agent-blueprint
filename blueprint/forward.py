"""正向：点子 / 不完整 PRD → 完整的 Agent Harness 产品方案。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from blueprint import vote
from blueprint.agent import supports_agent
from blueprint.knowledge import (ACCEPTANCE, EIGHT_QUESTIONS, FACT_KEYS, FEATURES, FIVE_ELEMENTS,
                                 load_prompt)
from blueprint.llm import BudgetExceeded, Runner
from blueprint.pipeline import StageRunner
from blueprint.render import render_plan
from blueprint.rules import select_components
from blueprint.schema import DESIGN_SCHEMA, EXTRACT_SCHEMA, FEATURE_IDS, MODEL_SCHEMA, REVIEW_SCHEMA


@dataclass
class Plan:
    input_text: str
    extract: dict
    elements: dict
    components: list[dict]
    design: dict
    review: dict
    design_attempts: int = 1
    runner: str = ""
    budget: dict = field(default_factory=dict)
    design_mode: str = "fixed"         # agent：领域建模 + 架构设计由 agent 查资料、自检后交卷；fixed：固定两步
    design_note: str = ""              # 没用上 agent 的原因

    @property
    def title(self) -> str:
        return self.extract.get("title") or "未命名产品"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "one_liner": self.extract.get("one_liner", ""),
            "facts": self.extract.get("facts", {}),
            "features": self.extract.get("features", {}),
            "unknowns": self.extract.get("unknowns", []),
            "elements": self.elements,
            "components": self.components,
            "design": self.design,
            "review": self.review,
            "design_attempts": self.design_attempts,
            "runner": self.runner,
            "budget": self.budget,
            "design_mode": self.design_mode,
            "design_note": self.design_note,
        }


def _fmt_fact_keys() -> str:
    return "\n".join(f"- {k}：{v}" for k, v in FACT_KEYS.items())


def _fmt_features() -> str:
    return "\n".join(f"- {f.id}（→ {f.component}）：{f.question}" for f in FEATURES)


def _fmt_questions() -> str:
    return "\n".join(f"{i + 1}. {q}" for i, q in enumerate(EIGHT_QUESTIONS))


def _fmt_elements() -> str:
    return "\n".join(f"- {k}：{v}" for k, v in FIVE_ELEMENTS.items())


def _fmt_acceptance() -> str:
    return "\n".join(f"- {name}：{desc}" for name, desc in ACCEPTANCE.values())


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


AGENT_RESERVE_CALLS = 3        # agent 之后还要留给审稿、重写后的复审等的调用次数


def vote_on_features(features: dict, material: str, stages: StageRunner,
                     log: Callable[[str], None] = print, label: str = "① 复核特征判断") -> dict:
    """另外独立判断两次特征，三票取多数（见 blueprint/vote.py）；不该投票时原样返回。"""
    if not vote.enabled(stages.runner):
        return features
    others = vote.cast(material, lambda stage, prompt, schema: stages.run(stage, prompt, schema, label))
    voted, changes = vote.majority(features, others)
    stages.save_json("stages/vote_features.json", {"original": features, "others": others, "changes": changes})
    log("    特征判断三次取多数：" + ("；".join(changes) if changes else "三次一致或多数同原判断"))
    return voted


def _agent_plan(runner: Runner) -> tuple[bool, str]:
    """要不要用 agent，以及不用时写进方案的原因（离线 mock 本来就没有 agent，不写原因）。"""
    if os.getenv("BLUEPRINT_AGENT", "").strip().lower() in ("off", "0", "false"):
        return False, "环境变量 BLUEPRINT_AGENT=off，使用固定流程"
    if not supports_agent(runner):
        return False, "" if getattr(runner, "name", "") == "mock" else "当前模型接入方式不支持工具调用，使用固定流程"
    if _agent_turns(runner) < 4:
        return False, "费用上限剩余的调用次数太少，使用固定流程（可调大 --max-calls）"
    return True, ""


def _agent_turns(runner: Runner) -> int:
    from blueprint.plan_agent import MAX_TURNS      # plan_agent 间接依赖本模块，延迟导入
    budget = getattr(runner, "budget", None)
    if budget is None:
        return MAX_TURNS
    return min(MAX_TURNS, budget.max_calls - budget.calls - AGENT_RESERVE_CALLS)


def run_plan(input_text: str, runner: Runner, out_dir: Path, resume: bool = False,
             log: Callable[[str], None] = print,
             feature_overrides: dict[str, dict] | None = None) -> tuple[Plan, Path]:
    """执行五步推导，返回 Plan 与 方案.md 的路径。

    feature_overrides：用这些判断覆盖需求拆解里同名特征的判断（加新需求时沿用上一版，见 blueprint/stability.py）。
    覆盖发生在拆解之后、选型之前，拆解阶段的缓存不受影响。
    """
    from blueprint.plan_agent import RESULT_SCHEMA as DESIGN_AGENT_SCHEMA, run_design_agent
    from blueprint.workspace import strip_auto_sections
    input_text = strip_auto_sections(input_text)     # 自动整理的 PRD 小节是产物，不当输入
    if not input_text.strip():
        raise ValueError("点子或 PRD 不能为空")
    stages = StageRunner(runner, out_dir, resume=resume, log=log,
                         context={"kind": "plan", "input": input_text})
    stages.save("input.md", input_text)

    # ① 需求拆解
    extract = stages.run("extract", load_prompt("extract").format(
        fact_keys=_fmt_fact_keys(), features=_fmt_features(),
        questions=_fmt_questions(), input=input_text), EXTRACT_SCHEMA, "① 需求拆解")
    if set(feature_overrides or {}) < set(FEATURE_IDS):     # 全部沿用上一版时没有要重新判断的特征
        extract = {**extract, "features": vote_on_features(extract.get("features", {}), input_text, stages, log)}
    if feature_overrides:
        extract = {**extract, "features": {**extract.get("features", {}), **feature_overrides}}

    # ③ 组件选型（规则，不调模型）：只依赖需求拆解，先算好，agent 设计时作为既定条件
    log("  ▶ ③ 组件选型（规则）")
    decisions = [d.to_dict() for d in select_components(extract.get("features", {}))]
    stages.save_json("stages/select.json", {"components": decisions})

    # ② 领域建模 + ④ 架构设计：能用 agent 就由 agent 查组件说明、自检后一起交卷；否则固定两步
    use_agent, design_note = _agent_plan(runner)
    elements: dict | None = None
    design: dict = {}
    review: dict = {}
    attempts = 0
    feedback = ""
    # ⑤ 审稿不过则带意见重写一次
    for attempt in range(2):
        attempts = attempt + 1
        if use_agent:
            try:
                out = stages.run_custom(
                    "design_agent" if attempt == 0 else "design_agent_retry",
                    {"input": input_text, "extract": extract, "components": decisions, "feedback": feedback,
                     "prompt": load_prompt("plan_agent")},
                    DESIGN_AGENT_SCHEMA,
                    "④ 领域建模 + 架构设计（agent）" if attempt == 0 else "④ 架构设计（按审稿意见重写，agent）",
                    lambda: run_design_agent(input_text, extract, decisions, runner, feedback, log=log,
                                             max_turns=_agent_turns(runner)))
                elements, design = out["elements"], out["design"]
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 —— agent 失败不能卡住推导，退回固定两步
                use_agent = False
                design_note = f"agent 未完成（{str(exc)[:160]}），已改用固定流程"
                log(f"  ⚠ {design_note}")
        if not use_agent:
            if elements is None:
                elements = stages.run("model", load_prompt("model").format(
                    elements=_fmt_elements(), facts_json=_dump(extract["facts"])), MODEL_SCHEMA, "② 领域建模")
            design = stages.run("design" if attempt == 0 else "design_retry", load_prompt("design").format(
                title=extract["title"], one_liner=extract.get("one_liner", ""),
                facts_json=_dump(extract["facts"]), elements_json=_dump(elements),
                components_json=_dump(decisions), review_feedback=feedback),
                DESIGN_SCHEMA, "④ 架构设计" if attempt == 0 else "④ 架构设计（按审稿意见重写）")
        plan_json = _dump({"facts": extract["facts"], "elements": elements,
                           "components": decisions, "design": design})
        review = stages.run("review" if attempt == 0 else "review_retry", load_prompt("review").format(
            acceptance=_fmt_acceptance(), input=input_text, plan_json=plan_json),
            REVIEW_SCHEMA, "⑤ 独立审稿" if attempt == 0 else "⑤ 独立审稿（复审）")
        if review.get("ok"):
            break
        feedback = "\n## 上一版审稿意见（必须逐条修正）\n" + "\n".join(
            f"- [{i.get('severity', '')}] {i.get('section', '')}：{i.get('problem', '')}"
            for i in review.get("issues", []))

    budget = getattr(runner, "budget", None)
    plan = Plan(input_text=input_text, extract=extract, elements=elements or {}, components=decisions,
                design=design, review=review, design_attempts=attempts,
                runner=getattr(runner, "name", ""),
                budget=budget.summary() if budget else {},
                design_mode="agent" if use_agent else "fixed", design_note=design_note)
    stages.save_json("plan.json", plan.to_dict())
    doc_path = stages.save("方案.md", render_plan(plan))
    return plan, doc_path
