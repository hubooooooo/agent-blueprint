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
}
PROVIDER_BY_KEY = {p["key"]: p for p in PROVIDERS.values()}

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


def has_real_key(path: Path = ENV_PATH) -> bool:
    return is_real_key(read_env(path).get("ANTHROPIC_API_KEY", ""))


def write_env(api_key: str, model: str, base_url: str | None, path: Path = ENV_PATH) -> None:
    """写入三项模型配置；.env 里其他配置（如 BLUEPRINT_MAX_OUTPUT_TOKENS）原样保留。"""
    managed = {"ANTHROPIC_API_KEY", "MODEL_ID", "ANTHROPIC_BASE_URL"}
    kept = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.partition("=")[0].strip()
            if name in managed or line.startswith("# 由引导工具生成"):
                continue
            kept.append(line)
    lines = ["# 由引导工具生成；密钥只保存在本机 .env，不会上传。",
             f"ANTHROPIC_API_KEY={api_key}", f"MODEL_ID={model}"]
    if base_url:
        lines.append(f"ANTHROPIC_BASE_URL={base_url}")
    while kept and not kept[0].strip():
        kept.pop(0)
    path.write_text("\n".join(lines + ([""] + kept if kept else [])) + "\n", encoding="utf-8")


def apply_to_process(api_key: str, model: str, base_url: str | None) -> None:
    """load_config 不覆盖已有环境变量，所以长驻进程（网页服务）改完配置要手动刷新一次。"""
    os.environ["ANTHROPIC_API_KEY"] = api_key
    os.environ["MODEL_ID"] = model
    if base_url:
        os.environ["ANTHROPIC_BASE_URL"] = base_url
    else:
        os.environ.pop("ANTHROPIC_BASE_URL", None)


def test_connection(base_url: str | None, api_key: str, model: str) -> tuple[bool, str]:
    try:
        from anthropic import Anthropic
    except ImportError:
        return False, "缺少 anthropic 依赖，请重新双击启动文件完成初始化"
    kwargs = {"api_key": api_key, "timeout": 30.0, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        client = Anthropic(**kwargs)
        resp = client.messages.create(
            model=model, max_tokens=16,
            messages=[{"role": "user", "content": "只回复两个字：成功"}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return True, f"连接成功，模型回复：{text.strip()[:30] or '(空)'}"
    except Exception as exc:  # noqa: BLE001 —— 把底层错误友好地转述给小白
        return False, f"连接失败：{exc}"
