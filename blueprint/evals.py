"""测试题运行器。

离线（默认）：
  1. 规则回归：expected.features → select_components == expected.components
  2. 管线回归：mock 跑通正向三题、反向两题，文档必须包含关键章节
真模型（--real）：
  正向三题各跑一次「需求拆解」，统计特征判断与标准答案的一致率；不跑后续阶段以省钱。
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from blueprint.rules import select_components

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"

PLAN_SECTIONS = ["待确认清单", "Step 1 · 需求拆解", "Step 2 · 领域建模", "Step 3 · 组件选型",
                 "分层架构图", "工具清单", "系统提示词草案", "安全边界与降级策略", "独立审稿意见"]
AUDIT_SECTIONS = ["一句话判定", "它现在是什么", "组件差距表", "五要素空位", "六条验收标准", "建议下一步", "证据附录"]


def forward_cases() -> list[Path]:
    return sorted(p for p in (EVALS / "forward").iterdir() if (p / "input.md").exists())


def reverse_cases() -> list[tuple[Path, Path]]:
    cases = []
    for p in sorted((EVALS / "reverse").iterdir()):
        if not (p / "expected.json").exists():
            continue
        target_file = p / "target.txt"
        target = (ROOT / target_file.read_text().strip()) if target_file.exists() else p
        cases.append((p, target))
    return cases


def check_rules(case: Path) -> list[str]:
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    features = {k: {"value": v, "evidence": ""} for k, v in expected["features"].items()}
    got = {d.id: d.decision for d in select_components(features)}
    return [f"{cid}: 期望 {want}，规则给出 {got.get(cid)}"
            for cid, want in expected["components"].items() if got.get(cid) != want]


def check_forward_pipeline(case: Path, runner, out_dir: Path) -> list[str]:
    from blueprint.forward import run_plan
    text = (case / "input.md").read_text(encoding="utf-8")
    plan, doc = run_plan(text, runner, out_dir, log=lambda _m: None)
    content = doc.read_text(encoding="utf-8")
    problems = [f"文档缺少章节「{s}」" for s in PLAN_SECTIONS if s not in content]
    if len(plan.components) != 17:
        problems.append(f"组件数应为 17，实际 {len(plan.components)}")
    if getattr(runner, "name", "") != "mock":      # 语义断言只对真模型有意义
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        for kw in expected.get("must_be_unknown_or_pending", []):
            if kw not in content:
                problems.append(f"文档应提到待确认项「{kw}」")
    return problems


def check_reverse_pipeline(case: Path, target: Path, runner, out_dir: Path) -> list[str]:
    from blueprint.reverse import run_audit
    audit, doc = run_audit(target, runner, out_dir, log=lambda _m: None)
    content = doc.read_text(encoding="utf-8")
    problems = [f"报告缺少章节「{s}」" for s in AUDIT_SECTIONS if s not in content]
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    comps = audit.inventory_brief["components"]
    for cid in expected.get("present_strong_or_weak", []):
        if comps[cid]["strength"] == "none":
            problems.append(f"{cid} 应被扫描到，实际 none")
    for cid in expected.get("present_none", []):
        if comps[cid]["strength"] != "none":
            problems.append(f"{cid} 不应被扫描到，实际 {comps[cid]['strength']}")
    for key in expected.get("acceptance_fail", []):
        if audit.acceptance[key]["status"] == "pass":
            problems.append(f"验收 {key} 应不通过，实际 pass")
    sdk = expected.get("llm_sdk")
    if sdk and sdk not in audit.inventory_brief["llm_sdks"]:
        problems.append(f"应识别出 SDK {sdk}")
    if not (out_dir / "本该有的PRD.md").exists():
        problems.append("缺少 本该有的PRD.md")
    return problems


def run_evals(real: bool = False, runner_factory: Callable[[], object] | None = None) -> int:
    failures = 0
    print("== 规则回归（正向）==")
    for case in forward_cases():
        problems = check_rules(case)
        print(f"  {'✅' if not problems else '❌'} {case.name}" + ("" if not problems else "\n     - " + "\n     - ".join(problems)))
        failures += bool(problems)

    from blueprint.mock import MockRunner
    tmp = Path(tempfile.mkdtemp(prefix="blueprint-evals-"))
    try:
        print("== 管线回归（离线 mock）==")
        for case in forward_cases():
            problems = check_forward_pipeline(case, MockRunner(), tmp / f"fwd-{case.name}")
            print(f"  {'✅' if not problems else '❌'} plan {case.name}" + ("" if not problems else "\n     - " + "\n     - ".join(problems)))
            failures += bool(problems)
        for case, target in reverse_cases():
            problems = check_reverse_pipeline(case, target, MockRunner(), tmp / f"rev-{case.name}")
            print(f"  {'✅' if not problems else '❌'} audit {case.name}" + ("" if not problems else "\n     - " + "\n     - ".join(problems)))
            failures += bool(problems)

        if real:
            if runner_factory is None:
                raise ValueError("real 模式需要 runner_factory")
            print("== 真实模型：特征判断准确率（只跑需求拆解）==")
            from blueprint.forward import _fmt_fact_keys, _fmt_features, _fmt_questions
            from blueprint.knowledge import load_prompt
            from blueprint.pipeline import SYSTEM
            from blueprint.schema import EXTRACT_SCHEMA
            total = 0
            agree = 0
            for case in forward_cases():
                runner = runner_factory()
                text = (case / "input.md").read_text(encoding="utf-8")
                expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))["features"]
                got = runner.complete("extract", SYSTEM, load_prompt("extract").format(
                    fact_keys=_fmt_fact_keys(), features=_fmt_features(),
                    questions=_fmt_questions(), input=text), EXTRACT_SCHEMA)
                diffs = []
                feature_agree = 0
                unknown_text = " ".join(got.get("unknowns", []))
                for kw in json.loads((case / "expected.json").read_text(encoding="utf-8")).get("must_be_unknown_or_pending", []):
                    if kw not in unknown_text:
                        diffs.append(f"待确认清单应提到「{kw}」")
                for fid, want in expected.items():
                    total += 1
                    have = got.get("features", {}).get(fid, {}).get("value")
                    if have == want:
                        agree += 1
                        feature_agree += 1
                    else:
                        diffs.append(f"{fid}: 期望 {want}，模型 {have}")
                failures += bool(diffs)
                print(f"  {case.name}: {feature_agree}/{len(expected)}" + ("" if not diffs else "\n     - " + "\n     - ".join(diffs)))
                (tmp / f"real-{case.name}.json").write_text(json.dumps(got, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  特征一致率：{agree}/{total} = {agree / total:.0%}")
    finally:
        if not real:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"  真实输出保存在 {tmp}")
    print("== 结果 ==", "全部通过" if failures == 0 else f"{failures} 项失败")
    return 0 if failures == 0 else 1
