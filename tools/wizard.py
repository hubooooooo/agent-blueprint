"""引导式 CLI：双击启动后，一问一答带小白跑通「配置模型 → 生成方案 / 检查项目」。

设计目标：零命令行知识。全程只需输入数字、粘贴 key 或路径，不要求记忆任何参数。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

PROVIDERS = {
    "1": {"key": "deepseek", "name": "DeepSeek（推荐）", "base": "https://api.deepseek.com/anthropic",
          "model": "deepseek-chat", "key_page": "https://platform.deepseek.com"},
    "2": {"key": "glm", "name": "智谱 GLM", "base": "https://open.bigmodel.cn/api/anthropic",
          "model": "glm-5.2", "key_page": "https://open.bigmodel.cn"},
    "3": {"key": "kimi", "name": "Kimi 月之暗面", "base": "https://api.moonshot.cn/anthropic",
          "model": "kimi-k2.7-code", "key_page": "https://platform.moonshot.cn"},
    "4": {"key": "minimax", "name": "MiniMax", "base": "https://api.minimaxi.com/anthropic",
          "model": "MiniMax-M3", "key_page": "https://platform.minimax.io"},
    "5": {"key": "anthropic", "name": "Anthropic 官方", "base": None,
          "model": "claude-sonnet-4-6", "key_page": "https://console.anthropic.com"},
}

LINE = "—" * 46


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\n已退出，再见。")
        sys.exit(0)


def ask_required(prompt: str) -> str:
    while True:
        value = ask(prompt)
        if value:
            return value
        print("这里不能为空，请再输入一次。")


def confirm(prompt: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    ans = ask(f"{prompt} {hint} ").lower()
    if not ans:
        return default
    return ans in ("y", "yes", "是", "1")


def read_env() -> dict:
    data: dict = {}
    if not ENV_PATH.exists():
        return data
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"\'')
    return data


def has_real_key() -> bool:
    key = read_env().get("ANTHROPIC_API_KEY", "")
    low = key.lower()
    return bool(key) and not any(m in low for m in ("xxx", "your", "placeholder", "sk-ant"))


def write_env(api_key: str, model: str, base_url: str | None) -> None:
    lines = [
        "# 由引导工具生成；密钥只保存在本机 .env，不会上传。",
        f"ANTHROPIC_API_KEY={api_key}",
        f"MODEL_ID={model}",
    ]
    if base_url:
        lines.append(f"ANTHROPIC_BASE_URL={base_url}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def configure_model() -> bool:
    while True:
        print(f"\n{LINE}")
        print("第一步：配置模型（引擎的“大脑”）")
        print(LINE)
        print("推荐 DeepSeek：便宜、国内可直连。先去官网申请一个 API Key 并充值几块钱：")
        print("  https://platform.deepseek.com")
        print()
        print("选择服务商：")
        for num, p in PROVIDERS.items():
            print(f"  {num}. {p['name']}")
        choice = ask("请输入数字（回车 = 1）: ") or "1"
        provider = PROVIDERS.get(choice, PROVIDERS["1"])
        print(f"\n已选：{provider['name']}")
        print(f"申请 Key 的网址：{provider['key_page']}")
        api_key = ask_required("把 API Key 粘贴到这里：")
        model = ask(f"模型名（回车用默认 {provider['model']}）：") or provider["model"]
        print("\n正在测试连接，稍等…")
        ok, msg = test_connection(provider["base"], api_key, model)
        if ok:
            print(f"✅ {msg}")
            write_env(api_key, model, provider["base"])
            print("已保存到本机 .env（只保存在你自己电脑上，不会上传）。")
            return True
        print(f"⚠️  {msg}")
        print("请检查：1) key 是否复制完整  2) 是否已充值  3) 服务商是否支持该地址")
        if not confirm("重新配置一次？", default=True):
            return False


def run(args: list[str]) -> None:
    print(f"\n{'=' * 46}", flush=True)
    print("正在推导，请稍候…（真实模型，首次稍慢）", flush=True)
    print("=" * 46 + "\n", flush=True)
    subprocess.run([sys.executable, "-m", "blueprint", *args], cwd=ROOT, stdin=subprocess.DEVNULL)


def latest_output() -> Path | None:
    out = ROOT / "out"
    if not out.exists():
        return None
    files = [p for p in out.rglob("*.md") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def after_run() -> None:
    latest = latest_output()
    if latest:
        print(f"\n✅ 结果文件：{latest}")
        if confirm("现在打开看看？", default=True):
            subprocess.run(["open", str(latest)])
    else:
        print("\n结果保存在 out/ 文件夹里。")
        if (ROOT / "out").exists():
            subprocess.run(["open", str(ROOT / "out")])


def do_plan() -> None:
    print(f"\n{LINE}")
    print("生成方案")
    print(LINE)
    print("可以直接打字描述想法，也可以粘贴一个 PRD / 需求文件路径。")
    src = ask_required("你的想法或文件路径：")
    run(["plan", src])
    after_run()


def do_audit() -> None:
    print(f"\n{LINE}")
    print("检查项目差距")
    print(LINE)
    print("把项目文件夹路径粘贴过来（可以直接把文件夹拖进这个窗口）。")
    project = ask_required("项目路径：")
    prd = ask("有需求文档（PRD）吗？有就粘贴路径，没有直接回车：")
    args = ["audit", project]
    if prd:
        args += ["--prd", prd]
    run(args)
    after_run()


def main() -> None:
    print(f"\n{'=' * 46}")
    print("Agent Blueprint 引导工具")
    print("=" * 46)

    if not has_real_key():
        print("\n这个工具需要真实的模型 API Key（离线演示是假数据，没有参考价值）。")
        print("推荐 DeepSeek：便宜、国内可直连，充值几块钱就能用很久。")
        print("申请地址：https://platform.deepseek.com")
        print("想先看看会拿到什么，可以打开 docs/examples/ 里的示例文档。")
        if confirm("已经有 Key 了，现在配置？", default=True):
            if not configure_model():
                print("\n配置没成功。申请好 Key 后，重新双击本文件即可。")
                return
        else:
            print("\n请先到 https://platform.deepseek.com 申请 Key，再重新双击本文件。")
            return

    while True:
        print(f"\n{LINE}")
        print("你想做什么？")
        print("  1. 我有一个想法 / 需求文档 → 生成方案")
        print("  2. 我有一个代码项目 → 检查差距")
        print("  3. 重新配置模型")
        print("  0. 退出")
        choice = ask("请输入数字：")
        if choice == "1":
            do_plan()
        elif choice == "2":
            do_audit()
        elif choice == "3":
            configure_model()
        elif choice == "0":
            print("\n再见！")
            break
        else:
            print("请输入 0–3 之间的数字。")


if __name__ == "__main__":
    main()
