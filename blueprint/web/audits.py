"""检查过的外部项目：把 out/audit-<名字>/ 下的结果整理成页面数据。只读，不调模型。

和命令行 `blueprint audit` 共用同一套目录，所以在终端里检查过的项目网页上也看得到。
产品靠 PRD.md 认，检查结果靠 audit.json / inventory.json 认，两者不会混在一起。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from blueprint.workspace import PRD_NAME, slugify

PREFIX = "audit-"
REPORT = "差距报告.md"
SUGGESTED_PRD = "本该有的PRD.md"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_audit_dir(d: Path) -> bool:
    return (d.name.startswith(PREFIX) and d.is_dir() and not (d / PRD_NAME).exists()
            and ((d / "audit.json").is_file() or (d / "inventory.json").is_file()))


def project_root(d: Path) -> str:
    """这个目录检查的是哪个项目。检查跑完前只有 inventory.json（第一步就写），也认。"""
    return _read_json(d / "audit.json").get("root") or _read_json(d / "inventory.json").get("root") or ""


def audit_dir_for(out_root: Path, project: Path) -> Path:
    """项目的检查结果放哪：out/audit-<文件夹名>/；同名的别的项目已占用时依次用 -2、-3，不互相覆盖。"""
    project = Path(project).resolve()
    base = PREFIX + slugify(project.name)
    for i in range(1, 1000):
        d = Path(out_root) / (base if i == 1 else f"{base}-{i}")
        if (d / PRD_NAME).exists():
            continue
        if not d.exists() or project_root(d) in ("", str(project)):
            return d
    raise ValueError("同名的检查结果太多了，先清理一下 out/ 目录")


def resolve_audit(out_root: Path, slug: str) -> Path:
    """slug 来自网址，只允许指向 out_root 下一层的检查结果目录。"""
    if not slug.startswith(PREFIX) or "/" in slug or "\\" in slug or slug.startswith("."):
        raise LookupError("检查结果不存在")
    d = Path(out_root) / slug
    if not is_audit_dir(d):
        raise LookupError("检查结果不存在")
    return d


def _verdict(report: str) -> str:
    m = re.search(r"## 一句话判定\s+\*\*(.+?)。?\*\*", report)
    return m.group(1) if m else ""


def audit_summary(d: Path) -> dict:
    audit = _read_json(d / "audit.json")
    root = project_root(d)
    report = d / REPORT
    gaps = audit.get("gaps") or []
    mtimes = [p.stat().st_mtime for p in (d / "audit.json", d / "inventory.json") if p.exists()]
    return {
        "slug": d.name,
        "name": Path(root).name if root else d.name.removeprefix(PREFIX),
        "title": audit.get("title", ""),
        "root": root,
        "finished": bool(audit) and report.is_file(),
        "completion": audit.get("completion"),
        "verdict": _verdict(report.read_text(encoding="utf-8")) if report.is_file() else "",
        "missing": sum(1 for g in gaps if g.get("verdict") == "缺失"),
        "weak": sum(1 for g in gaps if g.get("verdict") == "薄弱"),
        "mode": audit.get("mode", ""),
        "updated": max(mtimes) if mtimes else d.stat().st_mtime,
    }


def list_audits(out_root: Path) -> list[dict]:
    out_root = Path(out_root)
    if not out_root.is_dir():
        return []
    dirs = [d for d in out_root.glob(PREFIX + "*") if is_audit_dir(d)]
    return sorted((audit_summary(d) for d in dirs), key=lambda s: s["updated"], reverse=True)


def audit_detail(d: Path) -> dict:
    audit = _read_json(d / "audit.json")
    stats = audit.get("agent_stats") or {}

    def text(name: str) -> str:
        path = d / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    return {
        **audit_summary(d),
        "path": str(d.resolve()),
        # 报告文件终端和网页共用，网页上把命令行用法换成按钮名
        "report": text(REPORT).replace("加 `--rejudge`", "点右上角「重新判断」"),
        "suggested_prd": text(SUGGESTED_PRD),
        "mode_note": audit.get("mode_note", ""),
        "features_from": stats.get("features_from", ""),
        "files_seen": stats.get("files_seen", 0),
        "calls": (audit.get("budget") or {}).get("calls", 0),
    }
