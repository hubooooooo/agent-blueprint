"""一个产品累计花了多少：推导、加新需求、回答问题和加新需求时的对话都记进工作区的 usage.json。

每次推导只知道自己这一轮的用量（plan.json 里的 budget），断点续跑时沿用的阶段不计费；
这里把每一轮真实发生的调用加起来，网页上显示的才是这个产品到目前为止一共花了多少。
"""
import json
import threading
from pathlib import Path

USAGE_FILE = "usage.json"
KINDS = ("plan", "chat")
_FIELDS = ("calls", "input_tokens", "output_tokens", "cache_read_tokens")   # 旧文件没有 cache_read_tokens，读作 0
_lock = threading.Lock()   # 推导任务和对话可能同时写


def _empty() -> dict:
    return {k: 0 for k in _FIELDS}


def read_usage(ws: Path) -> dict:
    """{"total": {...}, "plan": {...}, "chat": {...}}；文件不存在或坏了都当 0。"""
    try:
        data = json.loads((ws / USAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = {kind: {k: int((data.get(kind) or {}).get(k, 0) or 0) for k in _FIELDS} for kind in KINDS}
    out["total"] = {k: sum(out[kind][k] for kind in KINDS) for k in _FIELDS}
    return out


def record_usage(ws: Path, kind: str, budget) -> None:
    """把一个 Budget 的用量加进 kind 名下。离线演示的 runner 没有 budget，什么都不记。"""
    if budget is None or not budget.calls:
        return
    with _lock:
        usage = read_usage(ws)
        for k in _FIELDS:
            usage[kind][k] += getattr(budget, k)
        data = {kind: usage[kind] for kind in KINDS}
        (ws / USAGE_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
