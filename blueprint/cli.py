"""命令行入口。

  python -m blueprint plan  idea.md [-o out/xxx] [--mock] [--resume]
  python -m blueprint audit ./project [--prd prd.md] [-o out/xxx] [--mock]
  python -m blueprint eval  [--real]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from blueprint.llm import Budget, BudgetExceeded, StageOutputInvalid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "out"


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿-]+", "-", text.strip())[:40].strip("-")
    return text or time.strftime("%Y%m%d-%H%M%S")


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
    unknowns = len(plan.extract.get("unknowns", []))
    if unknowns:
        print(f"⚠️  有 {unknowns} 个待确认问题，见文档开头。")
    return 0


def cmd_audit(args) -> int:
    project = Path(args.project)
    prd_text = Path(args.prd).read_text(encoding="utf-8") if args.prd else None
    out_dir = Path(args.out) if args.out else DEFAULT_OUT / f"audit-{_slug(project.resolve().name)}"
    from blueprint.reverse import run_audit
    print(f"反向审计：{project} → {out_dir}")
    audit, doc = run_audit(project, make_runner(args), out_dir, prd_text=prd_text, resume=args.resume)
    print(f"\n✅ 差距报告已生成：{doc}")
    print(f"   必选组件完成度 {int(audit.completion * 100)}%")
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
