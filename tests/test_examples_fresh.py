"""docs/examples 的真实产物带提示词指纹；提示词改了而示例没重新生成时给出警告（不失败）。"""
import importlib.util
import re
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [ROOT / "docs/examples/方案示例-玩具剧场-真实运行.md",
            ROOT / "docs/examples/差距报告示例-minimal-bot-真实运行.md"]


def _fingerprint() -> str:
    spec = importlib.util.spec_from_file_location("refresh_examples", ROOT / "tools/refresh_examples.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.prompts_fingerprint()


def test_examples_carry_prompt_fingerprint_and_warn_when_stale():
    if not (ROOT / "tools/refresh_examples.py").is_file():
        pytest.skip("学生包不带示例刷新脚本")
    current = _fingerprint()
    for path in EXAMPLES:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"prompts:([0-9a-f]{12})", text)
        assert m, f"{path.name} 缺少提示词指纹，请运行 tools/refresh_examples.py"
        if m.group(1) != current:
            warnings.warn(f"{path.name} 是用旧提示词（{m.group(1)}）生成的，当前为 {current}；"
                          "运行 .venv/bin/python tools/refresh_examples.py 重新生成", UserWarning)
