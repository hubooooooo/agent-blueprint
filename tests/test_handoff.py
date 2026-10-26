"""交接包（blueprint/handoff.py）：内容齐全、参考组件能独立运行、依赖表不漏、不带走密钥和环境目录。"""
import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from blueprint.forward import run_plan
from blueprint.handoff import AI_PROMPT, REFERENCE_DEPS, ROOT, build_handoff, handoff_filename, reference_components
from blueprint.knowledge import COMPONENT_BY_ID
from blueprint.mock import MockRunner
from blueprint.workspace import init_workspace, record_answers

IDEA = "家长拍一张玩具合影，AI 生成亲子剧情脚本。照片涉及隐私，默认不保存。生成内容必须过适龄审核。"


@pytest.fixture
def ws(tmp_path):
    ws = init_workspace(tmp_path, "玩具剧场", IDEA)
    run_plan((ws / "PRD.md").read_text(encoding="utf-8"), MockRunner(), ws, log=lambda _m: None)
    return ws


def unzip(data: bytes) -> dict[str, bytes]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}


def test_package_layout_and_guide(ws):
    record_answers(ws, [("孩子多大？", "6 到 8 岁")])
    files = unzip(build_handoff(ws))
    top = "玩具剧场-交接包/"
    assert all(n.startswith(top) for n in files)
    for name in ("交接说明.md", "给AI编程工具的提示词.md", "PRD.md", "方案.md", "plan.json", "迭代记录.md",
                 "参考组件/README.md", "参考组件/LICENSE", "参考组件/common/bootstrap.py"):
        assert top + name in files, name
    guide = files[top + "交接说明.md"].decode()
    for heading in ("## 第一版要做的组件", "### 需要找提出想法的人确认", "### 技术待定项", "## 怎么开始"):
        assert heading in guide
    assert "s03 权限系统" in guide and "`参考组件/s03_permission/`" in guide
    assert files[top + "给AI编程工具的提示词.md"].decode() == AI_PROMPT
    assert "6 到 8 岁" in files[top + "PRD.md"].decode()
    assert not any("/stages/" in n for n in files)                 # 中间产物不进包
    assert handoff_filename(ws) == "玩具剧场-交接包-V1.zip"


def test_skeleton_is_included_without_secrets_or_environments(ws):
    sk = ws / "skeleton"
    (sk / "agent.py").write_text("print('hi')\n", encoding="utf-8")
    (sk / ".env").write_text("ANTHROPIC_API_KEY=sk-real\n", encoding="utf-8")
    for junk in (".venv/lib/x.py", "node_modules/a/index.js", "__pycache__/agent.pyc"):
        (sk / junk).parent.mkdir(parents=True, exist_ok=True)
        (sk / junk).write_text("x", encoding="utf-8")
    names = set(unzip(build_handoff(ws)))
    assert "玩具剧场-交接包/skeleton/agent.py" in names
    assert not any(part in n for n in names for part in (".env", ".venv", "node_modules", "__pycache__"))


def test_requires_a_plan(tmp_path):
    ws = init_workspace(tmp_path, "只有点子", "一个想法")
    with pytest.raises(ValueError, match="还没有方案"):
        build_handoff(ws)


def test_reference_dependencies_are_declared():
    """code.py 里按路径加载别的组件（parents[1] / "sNN_xxx"）的，都要写进 REFERENCE_DEPS。"""
    folder_to_id = {Path(c.readme).parent.name: cid for cid, c in COMPONENT_BY_ID.items()}
    found: dict[str, set[str]] = {}
    for py in list(ROOT.glob("s[0-9][0-9]_*/code.py")) + list(ROOT.glob("s[0-9][0-9]_*/s[0-9][0-9]_parts/*.py")):
        owner = folder_to_id[py.relative_to(ROOT).parts[0]]
        for folder in re.findall(r'parents\[1\]\s*/\s*"(s\d\d_[a-z_]+)"', py.read_text(encoding="utf-8")):
            found.setdefault(owner, set()).add(folder_to_id[folder])
    assert {k: set(v) for k, v in REFERENCE_DEPS.items()} == found
    assert reference_components({"components": [{"id": "s16", "decision": "必选"}]}) == ["s09", "s15", "s16"]


def test_every_packaged_reference_imports_on_its_own(tmp_path):
    """解压后的 参考组件/ 是独立目录：每个 code.py 都要能在里面加载（不进入交互）。"""
    plan = {"components": [{"id": cid, "name": c.name, "decision": "必选", "reason": ""} for cid, c in COMPONENT_BY_ID.items()]}
    ws = init_workspace(tmp_path / "out", "全组件", "x")
    (ws / "plan.json").write_text(__import__("json").dumps(plan), encoding="utf-8")
    zipfile.ZipFile(io.BytesIO(build_handoff(ws))).extractall(tmp_path / "x")
    refs = tmp_path / "x" / "全组件-交接包" / "参考组件"
    env = {**os.environ, "ANTHROPIC_API_KEY": "sk-test-placeholder-0000", "MODEL_ID": "m"}
    for code in sorted(refs.glob("s*/code.py")):
        r = subprocess.run([sys.executable, "-c", f"import runpy, sys; sys.path.insert(0, '.'); runpy.run_path({str(code)!r}, run_name='handoff_check')"],
                           cwd=refs, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{code.parent.name}: {r.stderr[-500:]}"
