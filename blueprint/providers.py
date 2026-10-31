"""模型服务商配置：终端向导（tools/wizard.py）和网页界面（blueprint/web）共用这一份。"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

PROVIDERS = {
    "1": {"key": "deepseek", "name": "DeepSeek（推荐）", "base": "https://api.deepseek.com/anthropic",
          "model": "deepseek-v4-flash", "key_page": "https://platform.deepseek.com"},
    "2": {"key": "glm", "name": "智谱 GLM", "base": "https://open.bigmodel.cn/api/anthropic",
          "model": "glm-5.2", "key_page": "https://open.bigmodel.cn"},
    "3": {"key": "kimi", "name": "Kimi 月之暗面", "base": "https://api.moonshot.cn/anthropic",
          "model": "kimi-k2.7-code", "key_page": "https://platform.moonshot.cn"},
    "4": {"key": "minimax", "name": "MiniMax", "base": "https://api.minimaxi.com/anthropic",
          "model": "MiniMax-M3", "key_page": "https://platform.minimax.io"},
    "5": {"key": "anthropic", "name": "Anthropic 官方", "base": None,
          "model": "claude-sonnet-4-6", "key_page": "https://console.anthropic.com"},
    "6": {"key": "openai", "name": "OpenAI（GPT）", "base": None, "format": "openai",
          "model": "gpt-6-luna", "key_page": "https://platform.openai.com/api-keys"},
    "7": {"key": "openai-compat", "name": "OpenAI 格式的中转或其他服务", "base": None, "format": "openai",
          "custom_base": True, "model": "gpt-6-luna", "key_page": ""},
}
# format：接口格式，没写就是 anthropic（Anthropic Messages，含各家的 Anthropic 兼容地址）；
# openai 走 OpenAI Chat Completions（blueprint/openai_compat.py）。custom_base：接口地址由用户自己填。
for _p in PROVIDERS.values():
    _p.setdefault("format", "anthropic")
PROVIDER_BY_KEY = {p["key"]: p for p in PROVIDERS.values()}
_MANAGED = ("API_FORMAT", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_ID")

_PLACEHOLDER_MARKERS = ("xxx", "your", "placeholder")


def read_env(path: Path = ENV_PATH) -> dict:
    data: dict = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"\'')
    return data


def is_real_key(key: str) -> bool:
    low = key.strip().lower()
    return bool(low) and not any(m in low for m in _PLACEHOLDER_MARKERS)


def current_config(env: dict) -> dict:
    """.env 里现在的模型配置：{"format", "key", "base", "model"}。"""
    fmt = "openai" if env.get("API_FORMAT", "").strip().lower() == "openai" else "anthropic"
    prefix = "OPENAI" if fmt == "openai" else "ANTHROPIC"
    return {"format": fmt, "key": env.get(f"{prefix}_API_KEY", ""), "base": env.get(f"{prefix}_BASE_URL") or None,
            "model": env.get("MODEL_ID", "")}


def has_real_key(path: Path = ENV_PATH) -> bool:
    return is_real_key(current_config(read_env(path))["key"])


def _config_lines(api_key: str, model: str, base_url: str | None, fmt: str) -> list[str]:
    if fmt == "openai":
        return ["API_FORMAT=openai", f"OPENAI_API_KEY={api_key}", f"MODEL_ID={model}"] + \
            ([f"OPENAI_BASE_URL={base_url}"] if base_url else [])
    return [f"ANTHROPIC_API_KEY={api_key}", f"MODEL_ID={model}"] + \
        ([f"ANTHROPIC_BASE_URL={base_url}"] if base_url else [])


def write_env(api_key: str, model: str, base_url: str | None, path: Path = ENV_PATH, fmt: str = "anthropic") -> None:
    """写入模型配置，换接口格式时清掉另一种格式的配置；.env 里其他配置（如 BLUEPRINT_MAX_OUTPUT_TOKENS）原样保留。"""
    kept = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.partition("=")[0].strip()
            if name in _MANAGED or line.startswith("# 由引导工具生成"):
                continue
            kept.append(line)
    lines = ["# 由引导工具生成；密钥只保存在本机 .env，不会上传。"] + _config_lines(api_key, model, base_url, fmt)
    while kept and not kept[0].strip():
        kept.pop(0)
    path.write_text("\n".join(lines + ([""] + kept if kept else [])) + "\n", encoding="utf-8")


def apply_to_process(api_key: str, model: str, base_url: str | None, fmt: str = "anthropic") -> None:
    """load_config 不覆盖已有环境变量，所以长驻进程（网页服务）改完配置要手动刷新一次。"""
    for name in _MANAGED:
        os.environ.pop(name, None)
    for line in _config_lines(api_key, model, base_url, fmt):
        name, _, value = line.partition("=")
        os.environ[name] = value


def test_connection(base_url: str | None, api_key: str, model: str, fmt: str = "anthropic") -> tuple[bool, str]:
    try:
        from anthropic import Anthropic
    except ImportError:
        return False, "缺少 anthropic 依赖，请重新双击启动文件完成初始化"
    kwargs = {"api_key": api_key, "timeout": 30.0, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        if fmt == "openai":
            from blueprint.openai_compat import OpenAICompatClient
            client = OpenAICompatClient(api_key, base_url, timeout=30.0)
        else:
            client = Anthropic(**kwargs)
        resp = client.messages.create(
            model=model, max_tokens=16,
            messages=[{"role": "user", "content": "只回复两个字：成功"}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        text = text.strip()[:30]      # 思考模型在 16 个 token 里常常只来得及思考，没有正文也算连上了
        return True, f"连接成功，模型回复：{text}" if text else "连接成功"
    except Exception as exc:  # noqa: BLE001 —— 把底层错误友好地转述给小白
        return False, f"连接失败：{exc}"
