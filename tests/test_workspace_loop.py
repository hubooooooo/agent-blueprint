"""产品循环：init → plan → revise → verify 全部落在 out/<产品名>/ 里，PRD 有版本，迭代记录有条目。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from blueprint.mock import MockRunner
from blueprint.workspace import (PENDING_HEADING, bump_prd, component_diff, current_version,
                                 init_workspace, pending_versions, revise_workspace, verify_workspace)

ROOT = Path(__file__).resolve().parents[1]


def quiet(_msg):
    pass


def _init(tmp_path, idea="一个帮我每天整理邮件的助手"):
    return init_workspace(tmp_path, "邮件助手", idea)


def test_init_creates_workspace_layout(tmp_path):
    ws = _init(tmp_path)
    assert ws == tmp_path / "邮件助手"
    assert (ws / "PRD.md").is_file() and (ws / "迭代记录.md").is_file()
    assert (ws / "skeleton" / "README.md").is_file() and (ws / "prd").is_dir()
    prd = (ws / "PRD.md").read_text(encoding="utf-8")
    assert "一个帮我每天整理邮件的助手" in prd and current_version(prd) == 1
    assert PENDING_HEADING in prd


def test_init_refuses_to_overwrite(tmp_path):
    _init(tmp_path)
    with pytest.raises(ValueError, match="已存在"):
        _init(tmp_path)


def test_bump_prd_snapshots_and_appends_requirement(tmp_path):
    ws = _init(tmp_path)
    old, new, text = bump_prd(ws, "新增：支持微信消息\n细节略")
    assert (old, new) == (1, 2)
    assert (ws / "prd" / "V1.md").is_file()
    assert current_version(text) == 2
    assert "| V2 |" in text and "新增：支持微信消息" in text
    assert text.index(PENDING_HEADING) < text.index("### V2（")


def test_bump_prd_survives_ai_rewritten_prd_without_sections(tmp_path):
    ws = _init(tmp_path)
    (ws / "PRD.md").write_text("# PRD —— 邮件助手\n\n| 项 | 内容 |\n|---|---|\n| 当前版本 | V3 |\n\n正文", encoding="utf-8")
    old, new, text = bump_prd(ws, "再加一个需求")
    assert (old, new) == (3, 4)
    assert "## 版本演进记录" in text and PENDING_HEADING in text and "| V4 |" in text


def test_revise_reruns_plan_and_logs_component_diff(tmp_path):
    ws = _init(tmp_path)
    from blueprint.forward import run_plan
    run_plan((ws / "PRD.md").read_text(encoding="utf-8"), MockRunner(), ws, log=quiet)
    before = {c["id"]: c["decision"] for c in json.loads((ws / "plan.json").read_text())["components"]}
    assert before["s12"] == "必选"          # 「每天」是强信号

    result = revise_workspace(ws, "新增：需要定时每天早上 8 点跑，并且要审计每一次删除邮件的操作",
                              MockRunner(), log=quiet)
    assert result["new_version"] == 2
    after = {c["id"]: c["decision"] for c in json.loads((ws / "plan.json").read_text())["components"]}
    assert after["s03"] == "必选" and after["s04"] == "必选"
    assert ("s03", before["s03"], "必选") in result["diff"]
    log = (ws / "迭代记录.md").read_text(encoding="utf-8")
    assert "V2 · 新需求" in log and "选型变化" in log and "s03" in log
    assert (ws / "方案.md").read_text(encoding="utf-8").count("# PRD 推导方案") == 1


def test_revise_without_plan_only_bumps_prd(tmp_path):
    ws = _init(tmp_path)
    result = revise_workspace(ws, "只记一下", None, run_plan_flag=False, log=quiet)
    assert result["doc"] is None and result["new_version"] == 2
    assert "--no-plan" in (ws / "迭代记录.md").read_text(encoding="utf-8")
    assert not (ws / "plan.json").exists()


def test_revise_requires_workspace(tmp_path):
    with pytest.raises(ValueError, match="PRD.md"):
        revise_workspace(tmp_path / "nope", "x", None, run_plan_flag=False, log=quiet)


def test_verify_audits_skeleton_against_prd(tmp_path):
    ws = _init(tmp_path)
    with pytest.raises(ValueError, match="还没有代码"):
        verify_workspace(ws, MockRunner(), log=quiet)
    src = ROOT / "evals/reverse/minimal-bot"
    for p in src.rglob("*"):
        if p.is_file():
            dst = ws / "skeleton" / p.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(p.read_bytes())
    audit, doc = verify_workspace(ws, MockRunner(), log=quiet)
    assert doc == ws / "verify" / "差距报告.md" and doc.is_file()
    assert "· 验证" in (ws / "迭代记录.md").read_text(encoding="utf-8")


def test_component_diff_lists_changes_only():
    assert component_diff({"s03": "待确认", "s04": "必选"}, {"s03": "必选", "s04": "必选"}) == [("s03", "待确认", "必选")]


def test_cli_loop_end_to_end_mock(tmp_path, monkeypatch):
    env = dict(**{k: v for k, v in __import__("os").environ.items()}, BLUEPRINT_OUT=str(tmp_path))
    cmd = [sys.executable, "-m", "blueprint"]
    r = subprocess.run(cmd + ["init", "测试产品", "一个帮老师批改作文的助手", "--plan", "--mock"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    ws = tmp_path / "测试产品"
    assert (ws / "方案.md").is_file(), r.stdout
    r = subprocess.run(cmd + ["revise", str(ws), "新增：每周给家长发一份报告", "--mock"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "V2" in r.stdout, r.stdout + r.stderr
    assert current_version((ws / "PRD.md").read_text(encoding="utf-8")) == 2


def test_pending_versions_tracks_undigested_blocks(tmp_path):
    ws = _init(tmp_path)
    assert pending_versions((ws / "PRD.md").read_text(encoding="utf-8")) == []
    bump_prd(ws, "需求甲")
    bump_prd(ws, "需求乙")
    text = (ws / "PRD.md").read_text(encoding="utf-8")
    assert pending_versions(text) == ["V2", "V3"]
    digested = text.split(PENDING_HEADING)[0] + PENDING_HEADING + "\n\n（已消化）\n"
    assert pending_versions(digested) == []


def test_revise_warns_when_previous_requirement_not_digested(tmp_path):
    ws = _init(tmp_path)
    revise_workspace(ws, "第一轮需求", None, run_plan_flag=False, log=quiet)
    result = revise_workspace(ws, "第二轮需求", None, run_plan_flag=False, log=quiet)
    assert result["undigested"] == ["V2"]
    assert "还没消化" in (ws / "迭代记录.md").read_text(encoding="utf-8")


def test_revise_quick_mode_reselects_without_touching_design(tmp_path):
    ws = _init(tmp_path)
    from blueprint.forward import run_plan
    run_plan((ws / "PRD.md").read_text(encoding="utf-8"), MockRunner(), ws, log=quiet)
    plan_before = (ws / "plan.json").read_bytes()
    doc_before = (ws / "方案.md").read_bytes()
    runner = MockRunner()
    result = revise_workspace(ws, "新增：要审计每一次删除邮件的操作", runner, log=quiet, quick=True)
    assert runner.calls == ["extract"]                       # 只有一次模型调用
    assert result["doc"] is None and ("s03", "待确认", "必选") in result["diff"]
    assert (ws / "plan.json").read_bytes() == plan_before and (ws / "方案.md").read_bytes() == doc_before
    assert "快速模式" in (ws / "迭代记录.md").read_text(encoding="utf-8")
    # 之后全量重推时，需求拆解直接沿用快速模式的缓存
    runner2 = MockRunner()
    run_plan((ws / "PRD.md").read_text(encoding="utf-8"), runner2, ws, resume=True, log=quiet)
    assert "extract" not in runner2.calls


def test_plan_into_workspace_appends_log_entry(tmp_path):
    ws = _init(tmp_path)
    env = dict(**{k: v for k, v in __import__("os").environ.items()}, BLUEPRINT_OUT=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "blueprint", "plan", str(ws / "PRD.md"), "-o", str(ws), "--mock"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    log = (ws / "迭代记录.md").read_text(encoding="utf-8")
    assert "V1 · 方案推导" in log and "必选组件：" in log
    # 普通输出目录（不是工作区）不写迭代记录
    r = subprocess.run([sys.executable, "-m", "blueprint", "plan", "一个点子", "-o", str(tmp_path / "plain"), "--mock"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and not (tmp_path / "plain" / "迭代记录.md").exists()



def test_bump_snapshots_plan_and_history_readers(tmp_path):
    from blueprint.forward import run_plan
    from blueprint.workspace import log_entries, version_table
    ws = _init(tmp_path)
    run_plan((ws / "PRD.md").read_text(encoding="utf-8"), MockRunner(), ws, log=quiet)
    plan_v1 = (ws / "plan.json").read_text(encoding="utf-8")
    revise_workspace(ws, "要审计每一次删除\n细节", MockRunner(), log=quiet, source="网页界面·加新需求")
    assert (ws / "prd" / "V1.plan.json").read_text(encoding="utf-8") == plan_v1

    rows = version_table((ws / "PRD.md").read_text(encoding="utf-8"))
    assert [(r["version"], r["change"], r["source"]) for r in rows] == [
        (1, "初始需求", "首次需求"), (2, "要审计每一次删除", "网页界面·加新需求")]
    entries = log_entries(ws)
    assert [(e["version"], e["title"]) for e in entries] == [(1, "建立工作区"), (2, "新需求")]
    assert entries[1]["lines"][0] == "新需求：要审计每一次删除"


def test_revise_can_skip_undigested_warning(tmp_path):
    ws = _init(tmp_path)
    revise_workspace(ws, "第一轮需求", None, run_plan_flag=False, log=quiet)
    result = revise_workspace(ws, "第二轮需求", None, run_plan_flag=False, log=quiet, warn_undigested=False)
    assert result["undigested"] == ["V2"]
    assert "还没消化" not in (ws / "迭代记录.md").read_text(encoding="utf-8")


def test_log_uses_first_sentence_not_markdown_heading(tmp_path):
    ws = init_workspace(tmp_path, "烘焙助手", "### 一句话想法\n\n- 在微信上帮社区烘焙店回答顾客问题\n\n### 给谁用")
    log = (ws / "迭代记录.md").read_text(encoding="utf-8")
    assert "原始需求：在微信上帮社区烘焙店回答顾客问题" in log
