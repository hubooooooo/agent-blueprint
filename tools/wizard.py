"""引导式 CLI：双击启动后，一问一答带小白跑通「配置模型 → 生成方案 / 检查项目」。

设计目标：零命令行知识。全程只需输入数字、粘贴 key 或路径，不要求记忆任何参数。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blueprint.providers import PROVIDERS, has_real_key, test_connection, write_env  # noqa: E402

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


def after_run(preferred: Path | None = None) -> None:
    latest = preferred if preferred and preferred.exists() else latest_output()
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


def list_workspaces() -> list[Path]:
    out = ROOT / "out"
    return sorted((p.parent for p in out.glob("*/PRD.md")), key=lambda p: p.name) if out.exists() else []


def pick_workspace() -> Path | None:
    spaces = list_workspaces()
    if not spaces:
        print("\nout/ 里还没有产品工作区。先选「1」从一个想法开始。")
        return None
    print("\n已有的产品：")
    for i, ws in enumerate(spaces, 1):
        print(f"  {i}. {ws.name}")
    choice = ask("请输入数字：")
    if choice.isdigit() and 1 <= int(choice) <= len(spaces):
        return spaces[int(choice) - 1]
    print("没选中。")
    return None


def do_init() -> None:
    print(f"\n{LINE}")
    print("从一个想法开始一个产品（PRD、方案、骨架、迭代记录都放在 out/<产品名>/）")
    print(LINE)
    name = ask_required("给产品起个名字：")
    idea = ask_required("一句话说说你的想法：")
    run(["init", name, idea, "--plan"])
    import re as _re
    slug = _re.sub(r"[^\w一-鿿-]+", "-", name.strip())[:40].strip("-")
    after_run(ROOT / "out" / slug / "方案.md")
    print("\n下一步：回答方案里的待确认问题，然后让 AI 按方案把代码骨架写到 skeleton/ 里。")


def do_revise() -> None:
    print(f"\n{LINE}")
    print("给已有产品加新需求（PRD 升版 → 重推方案 → 记录选型变化）")
    print(LINE)
    ws = pick_workspace()
    if ws is None:
        return
    req = ask_required("新需求（一句话或一段话）：")
    run(["revise", str(ws), req])
    after_run(ws / "方案.md")
    print("\n下一步：让 AI 读 迭代记录.md 最新一条和 PRD.md 第 7 节，增量更新 skeleton/。")


def do_verify() -> None:
    print(f"\n{LINE}")
    print("用 PRD 对照代码骨架做差距检查")
    print(LINE)
    ws = pick_workspace()
    if ws is None:
        return
    run(["verify", str(ws)])
    after_run(ws / "verify" / "差距报告.md")


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
        print("  1. 我有一个想法 → 开始一个产品（建工作区 + 生成方案）")
        print("  2. 已有产品，我有新需求 → 升版 PRD、重推方案")
        print("  3. 已有产品，检查代码骨架是否对得上 PRD")
        print("  4. 只生成一份方案（不建工作区）")
        print("  5. 我有一个外部代码项目 → 检查差距")
        print("  6. 重新配置模型")
        print("  0. 退出")
        choice = ask("请输入数字：")
        if choice == "1":
            do_init()
        elif choice == "2":
            do_revise()
        elif choice == "3":
            do_verify()
        elif choice == "4":
            do_plan()
        elif choice == "5":
            do_audit()
        elif choice == "6":
            configure_model()
        elif choice == "0":
            print("\n再见！")
            break
        else:
            print("请输入 0–6 之间的数字。")


if __name__ == "__main__":
    main()
