"""探测模型服务商的工具调用能力：单次调用、多轮调用、一次多个调用。

用法（默认读 .env 里的 Key / 地址 / 模型）：
  .venv/bin/python tools/probe_tools.py
  .venv/bin/python tools/probe_tools.py --base-url https://xxx/anthropic --model glm-5.2
Key 也可以用环境变量 PROBE_API_KEY 临时传入，不写进 .env。

每项最多调用模型 8 次，三项合计不超过 24 次。结果只打印，不落盘。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blueprint.providers import read_env  # noqa: E402

MAX_CALLS = 8

READ_FILE = {
    "name": "read_file",
    "description": "读取项目里的一个文本文件，返回全文。",
    "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}},
                     "required": ["path"]},
}
FINISH = {
    "name": "finish",
    "description": "任务完成时调用，提交最终答案。",
    "input_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
}

# 多轮：一条线索链，必须一个接一个读下去才能拿到暗号
CHAIN = {
    "start.txt": "下一个文件是 notes/a.txt",
    "notes/a.txt": "下一个文件是 notes/b.txt",
    "notes/b.txt": "下一个文件是 lib/c.txt",
    "lib/c.txt": "下一个文件是 lib/d.txt",
    "lib/d.txt": "暗号是 蓝色猫头鹰",
}
# 并行：三个互不依赖的文件
NUMBERS = {"x.txt": "17", "y.txt": "25", "z.txt": "8"}

CASES = {
    "single": {
        "label": "单次调用",
        "files": {"README.md": "# 玩具剧场\n家长拍照，AI 生成亲子剧本。"},
        "tools": [READ_FILE],
        "prompt": "用 read_file 读一下 README.md，然后告诉我这个项目叫什么。",
    },
    "multi": {
        "label": "多轮调用",
        "files": CHAIN,
        "tools": [READ_FILE, FINISH],
        "prompt": "从 start.txt 开始，按文件里的提示一个接一个读下去，直到找到暗号，然后调用 finish 提交暗号。",
        "expect": "蓝色猫头鹰",
    },
    "parallel": {
        "label": "一次多个调用",
        "files": NUMBERS,
        "tools": [READ_FILE, FINISH],
        "prompt": "x.txt、y.txt、z.txt 三个文件各有一个数字，互不依赖。请在同一轮里同时调用三次 read_file 读取它们，"
                  "然后调用 finish 提交三个数字之和（只写数字）。",
        "expect": "50",
    },
}


def run_case(client, model: str, case: dict, max_tokens: int) -> dict:
    files = case["files"]
    messages = [{"role": "user", "content": case["prompt"]}]
    calls, max_parallel, tokens, read_paths = 0, 0, 0, []
    while calls < MAX_CALLS:
        response = client.messages.create(model=model, max_tokens=max_tokens, tools=case["tools"], messages=messages)
        calls += 1
        usage = getattr(response, "usage", None)
        tokens += (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        uses = [b for b in response.content if b.type == "tool_use"]
        max_parallel = max(max_parallel, len(uses))
        if not uses:
            text = "".join(getattr(b, "text", "") for b in response.content)
            if "expect" in case:
                return _result(False, f"没调用 finish 就停了（stop_reason={response.stop_reason}）：{text[:80]}",
                               calls, max_parallel, tokens)
            ok = bool(read_paths) and "玩具剧场" in text
            return _result(ok, f"读了 {read_paths}，回答：{text.strip()[:60]}", calls, max_parallel, tokens)
        results = []
        for use in uses:
            if not isinstance(use.input, dict):
                return _result(False, f"工具参数不是 JSON 对象：{use.input!r}", calls, max_parallel, tokens)
            if use.name == "finish":
                answer = str(use.input.get("answer", ""))
                ok = case.get("expect", "") in answer
                return _result(ok, f"提交答案：{answer[:60]}", calls, max_parallel, tokens)
            path = str(use.input.get("path", "")).lstrip("./")
            read_paths.append(path)
            content = files.get(path, f"错误：文件 {path} 不存在")
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": content})
        # 思考过程、文字、工具调用原样放回历史，部分服务商的思考模式要求这样
        messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]})
        messages.append({"role": "user", "content": results})
    return _result(False, f"{MAX_CALLS} 次调用内没完成", calls, max_parallel, tokens)


def _result(ok: bool, detail: str, calls: int, max_parallel: int, tokens: int) -> dict:
    return {"ok": ok, "detail": detail, "calls": calls, "max_parallel": max_parallel, "tokens": tokens}


def main() -> int:
    env = read_env()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=os.getenv("PROBE_BASE_URL") or env.get("ANTHROPIC_BASE_URL"))
    parser.add_argument("--model", default=os.getenv("PROBE_MODEL") or env.get("MODEL_ID"))
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--only", choices=list(CASES), action="append")
    parser.add_argument("--json", action="store_true", help="输出 JSON，便于汇总")
    args = parser.parse_args()
    api_key = os.getenv("PROBE_API_KEY") or env.get("ANTHROPIC_API_KEY", "")
    if not api_key or not args.model:
        print("缺少 Key 或模型：请配置 .env，或设置 PROBE_API_KEY 并传 --model")
        return 2

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key, base_url=args.base_url, timeout=120.0, max_retries=1)
    report = {"base_url": args.base_url or "(官方)", "model": args.model, "cases": {}}
    for key in args.only or list(CASES):
        try:
            report["cases"][key] = run_case(client, args.model, CASES[key], args.max_tokens)
        except Exception as exc:  # noqa: BLE001 —— 接口报错本身就是探测结果
            report["cases"][key] = _result(False, f"接口报错：{exc}"[:300], 0, 0, 0)
    report["supported"] = all(c["ok"] for c in report["cases"].values())

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"{report['base_url']}  {report['model']}")
        for key, case in report["cases"].items():
            mark = "✓" if case["ok"] else "✗"
            print(f"  {mark} {CASES[key]['label']}：{case['detail']}"
                  f"（调用 {case['calls']} 次，单轮最多 {case['max_parallel']} 个工具调用，{case['tokens']} tokens）")
        print("  结论：" + ("支持" if report["supported"] else "不支持，走退回路线"))
    return 0 if report["supported"] else 1


if __name__ == "__main__":
    sys.exit(main())
