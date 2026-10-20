"""组件 demo 的公共启动层。

17 个章节的 code.py 原本各自复制同一段启动代码：读 .env、建 Anthropic 客户端、取 MODEL_ID、
跑一个 input() 循环。这里把它们收拢到一处，并补上两件原来缺失的事：

1. 没有有效 API Key 时，启动即给出一行中文提示并退出，而不是在第一次对话时抛 401 堆栈；
2. 对话过程中的鉴权失败、网络不通、限流、模型不存在，转成一句话提示，不打印 Traceback。

用法（在 code.py 顶部）：
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common.bootstrap import make_client, resolve_model, run_repl, print_last_text
    client = make_client()
    MODEL = resolve_model()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DEFAULT_MODEL = "claude-sonnet-4-6"

_ENV_LOADED = False


def load_env() -> None:
    """加载引擎根目录的 .env（override=True，与各章节原行为一致）。

    设置 BLUEPRINT_SKIP_DOTENV=1 可跳过读取，供测试在干净环境下启动 demo。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if os.getenv("BLUEPRINT_SKIP_DOTENV") == "1":
        return
    from dotenv import load_dotenv
    # 不传路径：python-dotenv 会从本文件所在目录向上查找，第一个命中的就是引擎根目录的 .env。
    # 保持与各章节原来的 load_dotenv(override=True) 同一调用形式，测试里的桩函数也兼容。
    load_dotenv(override=True)
    # 走兼容网关时不能同时带官方的 AUTH_TOKEN，否则网关会拒绝
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def has_credentials() -> bool:
    """与 blueprint/llm.py 相同的判定：Key 非空且不是模板占位符。"""
    load_env()
    markers = ("xxx", "your", "placeholder")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        value = os.getenv(name, "").strip()
        if value and not any(m in value.lower() for m in markers):
            return True
    return False


def make_client():
    """构造 Anthropic 客户端；不在这里检查 Key，保证测试可以无 Key 导入模块。"""
    from anthropic import Anthropic
    load_env()
    return Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))


def resolve_model(default: str = DEFAULT_MODEL) -> str:
    load_env()
    return os.getenv("MODEL_ID") or default


def credentials_hint() -> str:
    return (
        "⛔ 未配置有效的 API Key，无法调用模型。\n"
        f"   请复制 {ROOT / '.env.example'} 为 .env，填入 ANTHROPIC_API_KEY 和 MODEL_ID；\n"
        "   也可以运行 python tools/wizard.py 一问一答完成配置。"
    )


def require_credentials() -> None:
    """交互式入口在开始对话前调用：没有 Key 直接退出，退出码 1。"""
    if not has_credentials():
        print(credentials_hint())
        sys.exit(1)


def friendly_api_error(exc: BaseException) -> str | None:
    """把 anthropic SDK 的常见异常翻译成一句话；不认识的返回 None。"""
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return None
    if isinstance(exc, anthropic.AuthenticationError):
        return "⛔ API Key 无效或已过期（401）。请检查 .env 里的 ANTHROPIC_API_KEY 与 ANTHROPIC_BASE_URL 是否匹配。"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "⛔ 该 Key 无权访问此模型（403）。请检查 MODEL_ID，或到供应商控制台确认权限。"
    if isinstance(exc, anthropic.NotFoundError):
        return f"⛔ 模型不存在或网关不认识（404）：MODEL_ID={os.getenv('MODEL_ID', '')!r}。请对照 .env.example 里的速查表。"
    if isinstance(exc, anthropic.RateLimitError):
        return "⛔ 触发限流或余额不足（429）。稍后重试，或到供应商控制台查看额度。"
    if isinstance(exc, anthropic.APITimeoutError):
        return "⛔ 请求超时。请检查网络，或换一个离你更近的网关。"
    if isinstance(exc, anthropic.APIConnectionError):
        return "⛔ 连不上模型服务。请检查网络、代理，以及 ANTHROPIC_BASE_URL 是否写对。"
    if isinstance(exc, anthropic.APIStatusError):
        return f"⛔ 模型服务返回错误（{exc.status_code}）：{getattr(exc, 'message', exc)}"
    return None


def guard(fn: Callable[[], None]) -> bool:
    """执行一轮对话；API 异常只打印一句提示。返回是否正常完成。"""
    try:
        fn()
        return True
    except Exception as exc:  # noqa: BLE001 - 只拦截能翻译的 SDK 异常
        hint = friendly_api_error(exc)
        if hint is None:
            raise
        print(hint)
        return False


def print_last_text(history: list) -> None:
    """打印 history 末尾那条 assistant 消息里的文本块；兼容 SDK 对象、dict 与纯字符串。"""
    if not history:
        return
    content = history[-1].get("content") if isinstance(history[-1], dict) else None
    if isinstance(content, str):
        print(content)
        return
    for block in content or []:
        if getattr(block, "type", None) == "text":
            print(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            print(block.get("text", ""))


def run_repl(name: str, banner: str, handle: Callable[[str], None], prompt: str | None = None) -> None:
    """标准交互循环：打印横幅 → 检查凭证 → 逐行读入 → 交给 handle。q / exit / 空行退出。"""
    print(banner)
    print("Enter a question, press Enter to send. Type q to quit.\n")
    require_credentials()
    prompt = prompt or f"\033[36m{name} >> \033[0m"
    while True:
        try:
            query = input(prompt)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        guard(lambda: handle(query))
        print()
