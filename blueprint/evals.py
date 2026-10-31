"""测试题运行器。

离线（默认）：
  1. 规则回归：expected.features → select_components == expected.components
  2. 管线回归：mock 跑通正向三题、反向两题，文档必须包含关键章节；
     并守住下限：标准答案判「放弃」的组件，mock 不得判成必选/二期
真模型（--real [--repeat N]）：
  正向三题各跑 N 次「需求拆解」（含特征多数票），统计特征判断与标准答案的一致率，单次判断与取多数分开统计；
  N > 1 时再统计多次运行之间不一致的特征数。不跑后续阶段以省钱。
真模型反向（--real-audit [--repeat N]）：
  反向各题用 agent 完整跑检查，核对组件强弱；agent_only 的题（关键词陷阱）只在这里判对错。
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
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    if getattr(runner, "name", "") != "mock":      # 语义断言只对真模型有意义
        for kw in expected.get("must_be_unknown_or_pending", []):
            if kw not in content:
                problems.append(f"文档应提到待确认项「{kw}」")
    else:                                          # mock 只守下限：标准答案「放弃」的组件不得被选上
        got = {c["id"]: c["decision"] for c in plan.components}
        for cid, want in expected["components"].items():
            if want == "放弃" and got.get(cid) in ("必选", "二期"):
                problems.append(f"{cid}: 标准答案为放弃，mock 却判 {got[cid]}（启发式过度激进）")
    return problems


def check_reverse_pipeline(case: Path, target: Path, runner, out_dir: Path):
    """返回 (问题列表, audit)。组件强弱看最终采用的结论：agent 模式是 agent 核实的，否则是扫描结果。"""
    from blueprint.reverse import run_audit
    # 题目目录里有标准答案 expected.json，agent 会读文件，必须先拿掉再检查
    project = out_dir.parent / f"{out_dir.name}-project"
    shutil.rmtree(project, ignore_errors=True)
    shutil.copytree(target, project, ignore=shutil.ignore_patterns("expected.json", "target.txt", "__pycache__"))
    audit, doc = run_audit(project, runner, out_dir, log=lambda _m: None)
    content = doc.read_text(encoding="utf-8")
    problems = [f"报告缺少章节「{s}」" for s in AUDIT_SECTIONS if s not in content]
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    present = {cid: c["strength"] for cid, c in audit.inventory_brief["components"].items()}
    present.update({g.id: g.present for g in audit.gaps})
    judge = audit.mode == "agent" or not expected.get("agent_only")   # 关键词陷阱题：快速扫描本来就会判错
    for cid in expected.get("present_strong_or_weak", []) if judge else []:
        if present[cid] == "none":
            problems.append(f"{cid} 应判有，实际 none")
    for cid in expected.get("present_not_strong", []) if judge else []:
        if present[cid] == "strong":
            problems.append(f"{cid} 只有关键词没有实现，不应判 strong")
    for cid in expected.get("present_none", []) if judge else []:
        if present[cid] != "none":
            problems.append(f"{cid} 应判 none，实际 {present[cid]}")
    for key in expected.get("acceptance_fail", []):
        if audit.acceptance[key]["status"] == "pass":
            problems.append(f"验收 {key} 应不通过，实际 pass")
    sdk = expected.get("llm_sdk")
    if sdk and sdk not in audit.inventory_brief["llm_sdks"]:
        problems.append(f"应识别出 SDK {sdk}")
    if not (out_dir / "本该有的PRD.md").exists():
        problems.append("缺少 本该有的PRD.md")
    return problems, audit


def run_evals(real: bool = False, runner_factory: Callable[[], object] | None = None,
              real_audit: bool = False, repeat: int = 1) -> int:
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
            problems, _audit = check_reverse_pipeline(case, target, MockRunner(), tmp / f"rev-{case.name}")
            print(f"  {'✅' if not problems else '❌'} audit {case.name}" + ("" if not problems else "\n     - " + "\n     - ".join(problems)))
            failures += bool(problems)

        if real:
            if runner_factory is None:
                raise ValueError("real 模式需要 runner_factory")
            print(f"== 真实模型：特征判断准确率（只跑需求拆解，每题 {repeat} 次）==")
            from blueprint import vote
            from blueprint.forward import _fmt_fact_keys, _fmt_features, _fmt_questions
            from blueprint.knowledge import load_prompt
            from blueprint.pipeline import SYSTEM
            from blueprint.schema import EXTRACT_SCHEMA
            total = agree = single_agree = 0
            flips = single_flips = features_seen = 0
            for case in forward_cases():
                text = (case / "input.md").read_text(encoding="utf-8")
                answer = json.loads((case / "expected.json").read_text(encoding="utf-8"))
                expected = answer["features"]
                singles, voteds = [], []
                for i in range(1, repeat + 1):
                    runner = runner_factory()
                    got = runner.complete("extract", SYSTEM, load_prompt("extract").format(
                        fact_keys=_fmt_fact_keys(), features=_fmt_features(),
                        questions=_fmt_questions(), input=text), EXTRACT_SCHEMA)
                    single = {fid: (got.get("features", {}).get(fid) or {}).get("value") for fid in expected}
                    voted = single
                    if vote.enabled(runner):
                        others = vote.cast(text, lambda stage, prompt, schema: runner.complete(stage, SYSTEM, prompt, schema))
                        voted = {fid: v["value"] for fid, v in vote.majority(got.get("features", {}), others)[0].items()}
                    singles.append(single)
                    voteds.append(voted)
                    diffs = []
                    unknown_text = " ".join(got.get("unknowns", []))
                    for kw in answer.get("must_be_unknown_or_pending", []):
                        if kw not in unknown_text:
                            diffs.append(f"待确认清单应提到「{kw}」")
                    feature_agree = 0
                    for fid, want in expected.items():
                        total += 1
                        single_agree += single[fid] == want
                        if voted[fid] == want:
                            agree += 1
                            feature_agree += 1
                        else:
                            diffs.append(f"{fid}: 期望 {want}，模型 {voted[fid]}"
                                         + (f"（单次判断 {single[fid]}）" if single[fid] != voted[fid] else ""))
                    failures += bool(diffs)
                    print(f"  {case.name} #{i}: {feature_agree}/{len(expected)}" + ("" if not diffs else "\n     - " + "\n     - ".join(diffs)))
                    (tmp / f"real-{case.name}-{i}.json").write_text(json.dumps(
                        {**got, "voted_features": voted}, ensure_ascii=False, indent=2), encoding="utf-8")
                features_seen += len(expected)
                flips += sum(len({v[fid] for v in voteds}) > 1 for fid in expected)
                single_flips += sum(len({v[fid] for v in singles}) > 1 for fid in expected)
            print(f"  特征一致率：取多数 {agree}/{total} = {agree / total:.0%}；单次判断 {single_agree}/{total} = {single_agree / total:.0%}")
            if repeat > 1:
                print(f"  多次运行结果不一致的特征：取多数 {flips}/{features_seen}；单次判断 {single_flips}/{features_seen}")

        if real_audit:
            if runner_factory is None:
                raise ValueError("real_audit 模式需要 runner_factory")
            print(f"== 真实模型：反向检查（agent，每题 {repeat} 次）==")
            for case, target in reverse_cases():
                for i in range(1, repeat + 1):
                    try:
                        problems, audit = check_reverse_pipeline(case, target, runner_factory(),
                                                                 tmp / f"real-rev-{case.name}-{i}")
                    except Exception as exc:  # noqa: BLE001 —— 一题接口出错不影响其余题目
                        print(f"  ❌ audit {case.name} #{i}：接口报错 {str(exc)[:120]}")
                        failures += 1
                        continue
                    if audit.mode != "agent":
                        problems.append(f"没有用上 agent：{audit.mode_note}")
                    b = audit.budget
                    cost = (f"调用 {b.get('calls', 0)} 次，{b.get('input_tokens', 0) + b.get('output_tokens', 0)} tokens（另有 {b.get('cache_read_tokens', 0)} 命中缓存），"
                            f"读过 {audit.agent_stats.get('files_seen', 0)} 个文件")
                    print(f"  {'✅' if not problems else '❌'} audit {case.name} #{i}（{cost}）"
                          + ("" if not problems else "\n     - " + "\n     - ".join(problems)))
                    failures += bool(problems)
    finally:
        if not (real or real_audit):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"  真实输出保存在 {tmp}")
    print("== 结果 ==", "全部通过" if failures == 0 else f"{failures} 项失败")
    return 0 if failures == 0 else 1
