"""命令行入口。

  python -m blueprint plan   idea.md [-o out/xxx] [--mock] [--resume]
  python -m blueprint audit  ./project [--prd prd.md] [-o out/xxx] [--mock]
  python -m blueprint eval   [--real]

  产品循环（全部在 out/<产品名>/ 里）：
  python -m blueprint init   "<产品名>" "<一句话点子>" [--plan]
  python -m blueprint revise out/<产品名> "<新需求>" [--no-plan]
  python -m blueprint verify out/<产品名>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from blueprint.llm import Budget, BudgetExceeded, StageOutputInvalid

ROOT = Path(__file__).resolve().parent.parent
# 输出根目录默认是引擎下的 out/；测试或特殊部署可用环境变量 BLUEPRINT_OUT 改到别处。
DEFAULT_OUT = Path(os.environ.get("BLUEPRINT_OUT") or ROOT / "out")


from blueprint.render import pending_summary  # noqa: E402
from blueprint.workspace import slugify as _slug  # noqa: E402


def make_runner(args) -> object:
    if getattr(args, "mock", False):
        from blueprint.mock import MockRunner
        return MockRunner()
    from blueprint.llm import AnthropicRunner
    budget = Budget(max_calls=args.max_calls, max_tokens=args.max_tokens)
    return AnthropicRunner(model=getattr(args, "model", None), budget=budget)


def cmd_plan(args) -> int:
    src = Path(args.input).expanduser()
    try:
        is_file = src.is_file()
    except OSError:
        is_file = False  # 多行或长 PRD 是正文，不能按文件名长度限制拒绝。
    if is_file:
        text = src.read_text(encoding="utf-8")
        name = src.stem
    else:
        text = args.input          # 允许直接把点子当参数传进来
        name = _slug(text[:40])
    out_dir = Path(args.out) if args.out else DEFAULT_OUT / _slug(name)
    from blueprint.forward import run_plan
    print(f"正向推导：{name} → {out_dir}")
    plan, doc = run_plan(text, make_runner(args), out_dir, resume=args.resume)
    print(f"\n✅ 方案已生成：{doc}")
    pending = pending_summary(plan)
    if pending:
        print(f"⚠️  待确认：{pending}，见文档开头的待确认清单。")
    _log_plan_in_workspace(out_dir, plan, doc)
    return 0


def _log_plan_in_workspace(out_dir: Path, plan, doc: Path) -> None:
    """输出目录如果是产品工作区（有 PRD.md 和 迭代记录.md），把这次推导记一条，保持循环记录完整。"""
    from blueprint.workspace import LOG_NAME, PRD_NAME, append_log, current_version, read_prd
    if not ((out_dir / PRD_NAME).is_file() and (out_dir / LOG_NAME).is_file()):
        return
    version = current_version(read_prd(out_dir))
    must = [c["id"] for c in plan.components if c["decision"] == "必选"]
    append_log(out_dir, f"V{version} · 方案推导", [
        f"方案：{doc.name}（模型 {plan.model_label}，审稿{'通过' if plan.review.get('ok') else '未完全通过，见文末意见'}）",
        f"必选组件：{'、'.join(must)}",
        f"待确认：{pending_summary(plan) or '无'}，见 方案.md 开头；回答写进 PRD.md 第 6 节",
        "人工验证结论：（待填）",
    ])


def cmd_audit(args) -> int:
    project = Path(args.project)
    prd_text = Path(args.prd).read_text(encoding="utf-8") if args.prd else None
    out_dir = Path(args.out) if args.out else DEFAULT_OUT / f"audit-{_slug(project.resolve().name)}"
    from blueprint.reverse import run_audit
    print(f"反向审计：{project} → {out_dir}")
    audit, doc = run_audit(project, make_runner(args), out_dir, prd_text=prd_text, resume=args.resume)
    print(f"\n✅ 差距报告已生成：{doc}")
    print(f"   必选组件信号覆盖率 {int(audit.completion * 100)}%")
    return 0


def _text_or_file(value: str) -> str:
    path = Path(value).expanduser()
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return value


def cmd_init(args) -> int:
    from blueprint.workspace import init_workspace
    ws = init_workspace(DEFAULT_OUT, args.name, _text_or_file(args.idea))
    print(f"✅ 工作区已创建：{ws}")
    print(f"   PRD.md · 迭代记录.md · skeleton/（骨架放这里）")
    if args.plan:
        from blueprint.forward import run_plan
        try:
            plan, doc = run_plan((ws / "PRD.md").read_text(encoding="utf-8"), make_runner(args), ws)
        except (BudgetExceeded, StageOutputInvalid) as exc:
            print(f"\n⛔ 工作区已建好，但方案推导中断：{exc}")
            print(f"   接着跑：.venv/bin/python -m blueprint plan \"{ws / 'PRD.md'}\" -o \"{ws}\" --resume")
            return 3
        _log_plan_in_workspace(ws, plan, doc)
        print(f"\n✅ 方案已生成：{doc}")
        pending = pending_summary(plan)
        if pending:
            print(f"⚠️  待确认：{pending}，见 方案.md 开头；回答后写进 PRD.md 第 6 节。")
    else:
        print(f"\n下一步：.venv/bin/python -m blueprint plan \"{ws / 'PRD.md'}\" -o \"{ws}\"")
    return 0


def cmd_revise(args) -> int:
    from blueprint.workspace import revise_workspace
    ws = Path(args.workspace)
    runner = None if args.no_plan else make_runner(args)
    result = revise_workspace(ws, _text_or_file(args.requirement), runner,
                              run_plan_flag=not args.no_plan, quick=args.quick)
    if result.get("undigested"):
        print(f"⚠️  上一轮新需求 {'、'.join(result['undigested'])} 还没消化，已写进迭代记录提醒。")
    print(f"\n✅ PRD 升到 V{result['new_version']}；迭代记录已追加：{ws / '迭代记录.md'}")
    if result["doc"] or args.quick:
        print(f"   方案已重推：{result['doc']}" if result["doc"] else "   快速模式：只重跑了需求拆解与选型，方案.md 未更新")
        if result["diff"]:
            print("   选型变化：" + "；".join(f"{c} {a} → {b}" for c, a, b in result["diff"]))
        else:
            print("   选型变化：无")
    print("   下一步：让 AI 消化 PRD.md 第 7 节的新需求 → 增量更新 skeleton/ → blueprint verify")
    return 0


def cmd_verify(args) -> int:
    from blueprint.workspace import verify_workspace
    ws = Path(args.workspace)
    audit, doc = verify_workspace(ws, make_runner(args))
    print(f"\n✅ 验证报告：{doc}")
    print(f"   必选组件信号覆盖率 {int(audit.completion * 100)}%；人工验证结论请填进 {ws / '迭代记录.md'}")
    return 0


def cmd_eval(args) -> int:
    from blueprint.evals import run_evals
    return run_evals(real=args.real, runner_factory=lambda: make_runner(args))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blueprint", description="Agent Blueprint 引擎：点子 → 方案；项目 → 差距报告")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-o", "--out", help="输出目录（默认 out/<名字>）")
        sp.add_argument("--mock", action="store_true", help="离线模式：不调模型，用启发式占位")
        sp.add_argument("--resume", action="store_true", help="沿用已完成阶段的结果")
        sp.add_argument("--model", help="覆盖 .env 的 MODEL_ID")
        sp.add_argument("--max-calls", type=int, default=16, help="费用护栏：最多调模型次数")
        sp.add_argument("--max-tokens", type=int, default=400_000, help="费用护栏：token 总量上限")

    sp = sub.add_parser("plan", help="正向：点子 / 不完整 PRD → 完整方案")
    sp.add_argument("input", help="点子文件路径，或直接一句话")
    common(sp)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("audit", help="反向：已有项目 → 差距报告")
    sp.add_argument("project", help="项目目录")
    sp.add_argument("--prd", help="可选：对照的 PRD 文件")
    common(sp)
    sp.set_defaults(func=cmd_audit)

    def model_opts(sp):
        sp.add_argument("--mock", action="store_true", help="离线模式：不调模型，用启发式占位")
        sp.add_argument("--model", help="覆盖 .env 的 MODEL_ID")
        sp.add_argument("--max-calls", type=int, default=16, help="费用护栏：最多调模型次数")
        sp.add_argument("--max-tokens", type=int, default=400_000, help="费用护栏：token 总量上限")

    sp = sub.add_parser("init", help="产品循环①：新建 out/<产品名>/ 工作区（PRD 模板、迭代记录、skeleton/）")
    sp.add_argument("name", help="产品名（用作目录名）")
    sp.add_argument("idea", help="一句话点子，或点子文件路径")
    sp.add_argument("--plan", action="store_true", help="创建后立即推导方案")
    model_opts(sp)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("revise", help="产品循环③：新需求 → PRD 升版 → 重推方案 → 记录选型变化")
    sp.add_argument("workspace", help="工作区目录，如 out/<产品名>")
    sp.add_argument("requirement", help="新需求文本，或文件路径")
    sp.add_argument("--no-plan", action="store_true", help="只升版 PRD 和记录，不重推方案")
    sp.add_argument("--quick", action="store_true", help="只重跑需求拆解与选型（1 次调用），不重做架构设计与审稿")
    model_opts(sp)
    sp.set_defaults(func=cmd_revise)

    sp = sub.add_parser("verify", help="产品循环④：用 PRD 对照 skeleton/ 做差距检查，报告写入 verify/")
    sp.add_argument("workspace", help="工作区目录，如 out/<产品名>")
    model_opts(sp)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("eval", help="跑测试题（默认离线）")
    sp.add_argument("--real", action="store_true", help="用真实模型跑正向测试题并统计特征判断准确率")
    common(sp)
    sp.set_defaults(func=cmd_eval)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except BudgetExceeded as exc:
        print(f"\n⛔ 费用护栏触发：{exc}。已完成的阶段已保存，可加 --resume 继续。")
        sys.exit(2)
    except StageOutputInvalid as exc:
        print(f"\n⛔ 模型输出不合格式：{exc}。可加 --resume 重试失败的阶段。")
        sys.exit(3)
    except (OSError, ValueError) as exc:
        print(f"\n⛔ {exc}")
        sys.exit(1)
