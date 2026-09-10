"""正向：点子 / 不完整 PRD → 完整的 Agent Harness 产品方案。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from blueprint.knowledge import (ACCEPTANCE, EIGHT_QUESTIONS, FACT_KEYS, FEATURES, FIVE_ELEMENTS,
                                 load_prompt)
from blueprint.llm import Runner
from blueprint.pipeline import StageRunner
from blueprint.render import render_plan
from blueprint.rules import select_components
from blueprint.schema import DESIGN_SCHEMA, EXTRACT_SCHEMA, MODEL_SCHEMA, REVIEW_SCHEMA


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


def run_plan(input_text: str, runner: Runner, out_dir: Path, resume: bool = False,
             log: Callable[[str], None] = print) -> tuple[Plan, Path]:
    """执行五步推导，返回 Plan 与 方案.md 的路径。"""
    if not input_text.strip():
        raise ValueError("点子或 PRD 不能为空")
    stages = StageRunner(runner, out_dir, resume=resume, log=log,
                         context={"kind": "plan", "input": input_text})
    stages.save("input.md", input_text)

    # ① 需求拆解
    extract = stages.run("extract", load_prompt("extract").format(
        fact_keys=_fmt_fact_keys(), features=_fmt_features(),
        questions=_fmt_questions(), input=input_text), EXTRACT_SCHEMA, "① 需求拆解")

    # ② 领域建模
    elements = stages.run("model", load_prompt("model").format(
        elements=_fmt_elements(), facts_json=_dump(extract["facts"])), MODEL_SCHEMA, "② 领域建模")

    # ③ 组件选型（规则，不调模型）
    log("  ▶ ③ 组件选型（规则）")
    decisions = [d.to_dict() for d in select_components(extract.get("features", {}))]
    stages.save_json("stages/select.json", {"components": decisions})

    # ④ 架构设计 + ⑤ 审稿（不过审则带意见重写一次）
    design: dict = {}
    review: dict = {}
    attempts = 0
    feedback = ""
    for attempt in range(2):
        attempts = attempt + 1
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
    plan = Plan(input_text=input_text, extract=extract, elements=elements, components=decisions,
                design=design, review=review, design_attempts=attempts,
                runner=getattr(runner, "name", ""),
                budget=budget.summary() if budget else {})
    stages.save_json("plan.json", plan.to_dict())
    doc_path = stages.save("方案.md", render_plan(plan))
    return plan, doc_path
