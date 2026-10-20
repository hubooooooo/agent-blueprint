"""s13 / s15 按小节拆成 *_parts/ 文件；code.py 的文档字符串必须列出每个分节文件和每个 `# -- 小节 --` 标记。"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("chapter", ["s13_agent_teams", "s15_integrated_harness"])
def test_docstring_lists_every_part_and_section_marker(chapter):
    folder = ROOT / chapter
    source = (folder / "code.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(source)) or ""
    parts = sorted(folder.glob("s[0-9][0-9]_parts/p[0-9][0-9]_*.py"))
    assert len(parts) >= 10, "分节文件缺失"
    missing_files = [p.name for p in parts if p.name not in doc]
    assert not missing_files, f"{chapter} 文档字符串没列出分节文件：{missing_files}"
    markers = []
    for part in parts:
        markers += re.findall(r"^# -- (.+?) --$", part.read_text(encoding="utf-8"), re.M)
    assert markers, "分节里没有 # -- 小节 -- 标记"
    missing = [m for m in markers if m not in doc]
    assert not missing, f"{chapter} 文档字符串分节地图漏了：{missing}"


@pytest.mark.parametrize("chapter", ["s13_agent_teams", "s15_integrated_harness"])
def test_code_py_is_only_docstring_and_loader(chapter):
    source = (ROOT / chapter / "code.py").read_text(encoding="utf-8")
    assert source.count("\n") < 150, "code.py 应只剩文档字符串和加载器；新代码请写进分节文件"
    assert "_load_parts(globals())" in source
