"""用当前提示词重新生成 docs/examples 里的两份真实产物，并在文件头写入提示词指纹。

用法（引擎根目录，需要有效 Key）：
    .venv/bin/python tools/refresh_examples.py            # 重新推导 + 复制
    .venv/bin/python tools/refresh_examples.py --copy-only # 只从 out/ 复制（已经跑过 plan/audit）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 只算生成示例时用到的提示词：chat_*.md 是网页对话用的，revise_*.md 只在加新需求时用，改它们不影响方案和差距报告示例。
PROMPT_FILES = sorted(p for p in (ROOT / "blueprint/knowledge/prompts").glob("*.md")
                      if not p.name.startswith(("chat_", "revise_"))) + [ROOT / "blueprint/knowledge/__init__.py"]
EXAMPLES = ROOT / "docs/examples"
PLAN_OUT = ROOT / "out/toy-theater-real"
AUDIT_OUT = ROOT / "out/audit-minimal-bot-real"
# 题目目录里有标准答案 expected.json，反向检查的 agent 会读文件，所以先复制一份去掉它再检查
AUDIT_TARGET = ROOT / "out/minimal-bot"


def prompts_fingerprint() -> str:
    h = hashlib.sha256()
    for path in PROMPT_FILES:
        h.update(path.name.encode()); h.update(path.read_bytes())
    return h.hexdigest()[:12]


def _usage(path: Path) -> str:
    try:
        b = json.loads(path.read_text(encoding="utf-8")).get("budget", {})
        return f"{b.get('calls', '?')} 次调用、输入 {b.get('input_tokens', '?')} / 输出 {b.get('output_tokens', '?')} tokens"
    except (OSError, ValueError):
        return "用量未知"


def _write(src: Path, dst: Path, note: str) -> None:
    text = src.read_text(encoding="utf-8").replace(str(ROOT) + "/", "<引擎目录>/")
    first, rest = text.split("\n", 1)
    dst.write_text(first + "\n\n" + note + rest.lstrip("\n"), encoding="utf-8")
    print("已更新", dst.relative_to(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--copy-only", action="store_true")
    args = ap.parse_args()
    py = sys.executable
    if not args.copy_only:
        subprocess.run([py, "-m", "blueprint", "plan", str(ROOT / "evals/forward/toy-theater/input.md"), "-o", str(PLAN_OUT)], cwd=ROOT, check=True)
        shutil.rmtree(AUDIT_TARGET, ignore_errors=True)
        shutil.copytree(ROOT / "evals/reverse/minimal-bot", AUDIT_TARGET,
                        ignore=shutil.ignore_patterns("expected.json", "__pycache__"))
        subprocess.run([py, "-m", "blueprint", "audit", str(AUDIT_TARGET), "-o", str(AUDIT_OUT)], cwd=ROOT, check=True)
    fp = prompts_fingerprint()
    date = time.strftime("%Y-%m-%d")
    import os
    model = os.getenv("MODEL_ID") or "（见 .env）"
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env"); model = os.getenv("MODEL_ID", model)
    _write(PLAN_OUT / "方案.md", EXAMPLES / "方案示例-玩具剧场-真实运行.md",
           f"> ⚠️ 本文件是引擎**真实运行产物**，未经人工修改：模型 {model}，{date} 生成，提示词指纹 `prompts:{fp}`。\n"
           f"> 输入为 [evals/forward/toy-theater/input.md](../../evals/forward/toy-theater/input.md)，{_usage(PLAN_OUT / 'plan.json')}。\n"
           "> 审稿没有完全通过是正常的：独立审稿本来就该把方案里的矛盾挑出来，这些意见就是你下一轮要回答的问题。\n\n")
    _write(AUDIT_OUT / "差距报告.md", EXAMPLES / "差距报告示例-minimal-bot-真实运行.md",
           f"> ⚠️ 本文件是引擎**真实运行产物**，未经人工修改：模型 {model}，{date} 生成，提示词指纹 `prompts:{fp}`。\n"
           f"> 被审计项目为 [evals/reverse/minimal-bot](../../evals/reverse/minimal-bot)（去掉标准答案 expected.json 后的副本），{_usage(AUDIT_OUT / 'audit.json')}。\n"
           "> 复核有异议也是正常的：复核会质疑打分阶段的推测性结论，这正是两阶段设计的目的。\n\n")
    print("提示词指纹：", fp)


if __name__ == "__main__":
    main()
