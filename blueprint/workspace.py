"""产品工作区：把「点子 → PRD → 方案 → 骨架 → 验证 → 新需求」整个循环固定在 out/<产品名>/ 里。

目录约定（只此一处，别的地方不写）：

    out/<产品名>/
    ├── PRD.md          当前版本的需求文档（给 AI 看的，含版本记录、待确认与回答、待消化的新需求）
    ├── prd/V1.md …     每次升版前的快照
    ├── 方案.md、plan.json、stages/   引擎推导产物（blueprint plan / revise 写入）
    ├── skeleton/       代码骨架：可独立运行的项目，由 AI 按方案生成和增量修改
    ├── verify/         blueprint verify 的差距报告（PRD 对照 skeleton/）
    └── 迭代记录.md     每一轮：版本、新需求、选型变化、骨架待办、人工验证结论

命令：
    blueprint init   "<产品名>" "<一句话点子>"      建工作区（可加 --plan 立即推导）
    blueprint plan   out/<产品名>/PRD.md -o out/<产品名>
    blueprint revise out/<产品名> "<新需求>"        PRD 升版 → 重推方案 → 记录选型变化
    blueprint verify out/<产品名>                    用 PRD 对照 skeleton/ 做差距检查
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from blueprint.pipeline import atomic_write
from blueprint.render import pending_summary

PRD_NAME = "PRD.md"
LOG_NAME = "迭代记录.md"
SKELETON_DIR = "skeleton"
HISTORY_DIR = "prd"
VERIFY_DIR = "verify"
PENDING_HEADING = "## 7. 新增需求（待消化）"
# 网页界面自动整理的小节（PRD 第 2–5 节，见 blueprint/prd_fill.py）带这个标记。它们是给人和交接包看的产物，
# 不是推导的输入：推导前会被 strip_auto_sections 去掉，否则里面的「待确认」会被再拆成新问题，越滚越多。
AUTO_MARK = "<!-- agent-blueprint:auto -->"


def strip_auto_sections(prd_text: str) -> str:
    """去掉带 AUTO_MARK 的小节正文，只留标题。没有标记时原样返回。"""
    if AUTO_MARK not in prd_text:
        return prd_text
    parts = re.split(r"(?m)^(?=## )", prd_text)
    return "".join(p.split("\n", 1)[0] + "\n\n" if AUTO_MARK in p else p for p in parts)


# PRD 模板里写给人和 AI 工具看的说明（工作区规矩、迭代方式、各节的括号提示）。它们不是需求，
# 原样交给推导会被拆成「约束」和工具，还会冒出「工作区写文件算不算工具」这类怪问题。
_TEMPLATE_ROW = re.compile(r"(?m)^\|\s*(工作区|迭代方式)\s*\|.*\n?")


def _template_notes() -> set[str]:
    lines = (l.strip() for l in PRD_TEMPLATE.splitlines())
    return {l for l in lines if l.startswith("（") and l.endswith("）")}


def derivation_text(prd_text: str) -> str:
    """交给推导和验收的 PRD：去掉自动整理的小节和模板说明，用户写的内容一字不动。"""
    text = _TEMPLATE_ROW.sub("", strip_auto_sections(prd_text))
    notes = _template_notes()
    text = "\n".join(l for l in text.split("\n") if l.strip() not in notes)
    return re.sub(r"\n{3,}", "\n\n", text)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w一-鿿-]+", "-", text.strip())[:40].strip("-")
    return text or time.strftime("%Y%m%d-%H%M%S")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


PRD_TEMPLATE = """# PRD —— {name}

| 项 | 内容 |
|---|---|
| 产品名 | {name} |
| 当前版本 | V1 |
| 状态 | 迭代中 |
| 工作区 | `out/{slug}/`：PRD、方案、骨架（skeleton/）、验证报告、迭代记录都在这里，不要写到别处 |
| 迭代方式 | 新需求 → `blueprint revise` 升版 PRD → 重推方案 → 增量更新 skeleton/ → `blueprint verify` → 人工验证 → 下一轮 |

## 版本演进记录

| 版本 | 日期 | 变更 | 来源 |
|---|---|---|---|
| V1 | {date} | 初始需求 | 首次需求 |

## 1. 原始需求（逐字保留，不改写）

{idea}

## 2. 需求拆解

（由 AI 按 BLUEPRINT.md Step 1 填写：目标 / 用户 / 核心闭环 / 交付物 / 边界 / 约束；不知道的标「待确认」，不要编。）

## 3. 功能需求

（FR1、FR2 …，每条标注引入版本，例如「V1」「V2 新增」。）

## 4. 边界与红线

## 5. 成功指标（可度量）

## 6. 待确认问题与回答

（问题从 方案.md 的「待确认清单」搬来；用户的回答写在问题下方并注明日期。没回答的保留，不要删。）

{pending_heading}

（`blueprint revise` 会把新需求追加到这里。AI 把它们消化进上面各节、更新 skeleton/ 之后，清空本节，并在版本记录里补一行「已消化」。）
"""

LOG_TEMPLATE = """# 迭代记录 —— {name}

每一轮循环记一条。人工验证结论由人来填，AI 不要替人写「验证通过」。

## {date} · V1 · 建立工作区

- 原始需求：{idea_short}
- 下一步：`blueprint plan out/{slug}/PRD.md -o out/{slug}`（或已用 --plan 推导），回答 方案.md 的待确认清单，再让 AI 生成 skeleton/
- 人工验证结论：（待填）
"""

SKELETON_README = """# skeleton/ —— 代码骨架放这里

- 由 AI 按 `../方案.md` 生成，可独立运行：自带 requirements.txt、.env.example、README。
- 这是唯一允许写产品代码的位置，不要写到桌面、引擎目录其他位置或别的文件夹。
- 每一轮新需求只做增量修改，不要整目录重建；人工改过的文件要保留。
- 验证：在引擎根目录运行 `blueprint verify out/<产品名>`，差距报告写入 `../verify/`。
"""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    """第一行有内容的正文：跳过 Markdown 标题和列表符号（网页对话整理出的需求以「### 一句话想法」开头）。"""
    for line in text.strip().splitlines():
        line = line.strip().lstrip("-*> ").strip()
        if line and not line.startswith("#"):
            return line
    return text.strip().splitlines()[0] if text.strip() else ""


def init_workspace(out_root: Path, name: str, idea: str) -> Path:
    name = name.strip()
    if not name:
        raise ValueError("产品名不能为空")
    if not idea.strip():
        raise ValueError("点子不能为空")
    slug = slugify(name)
    ws = Path(out_root) / slug
    if (ws / PRD_NAME).exists():
        raise ValueError(f"工作区已存在：{ws / PRD_NAME}。要加需求请用 blueprint revise，要重来请换个产品名。")
    (ws / HISTORY_DIR).mkdir(parents=True, exist_ok=True)
    (ws / SKELETON_DIR).mkdir(parents=True, exist_ok=True)
    atomic_write(ws / PRD_NAME, PRD_TEMPLATE.format(name=name, slug=slug, date=_today(),
                                                    idea=idea.strip(), pending_heading=PENDING_HEADING))
    atomic_write(ws / LOG_NAME, LOG_TEMPLATE.format(name=name, slug=slug, date=_today(),
                                                    idea_short=_first_sentence(idea)[:80]))
    readme = ws / SKELETON_DIR / "README.md"
    if not readme.exists():
        atomic_write(readme, SKELETON_README)
    return ws


# ---------------------------------------------------------------------------
# PRD 版本操作
# ---------------------------------------------------------------------------

def read_prd(ws: Path) -> str:
    path = Path(ws) / PRD_NAME
    if not path.is_file():
        raise ValueError(f"不是产品工作区（缺少 {PRD_NAME}）：{ws}。先用 blueprint init 创建。")
    return path.read_text(encoding="utf-8")


def current_version(prd_text: str) -> int:
    m = re.search(r"\|\s*当前版本\s*\|\s*V(\d+)", prd_text)
    return int(m.group(1)) if m else 1


def _bump_header(prd_text: str, new_version: int) -> str:
    text, n = re.subn(r"(\|\s*当前版本\s*\|\s*)V\d+", rf"\g<1>V{new_version}", prd_text, count=1)
    return text if n else prd_text


def _append_history_row(prd_text: str, row: str) -> str:
    """在「版本演进记录」表格末尾追加一行；找不到表格就把整节补上。"""
    m = re.search(r"^## 版本演进记录\s*$", prd_text, re.M)
    if not m:
        return prd_text.rstrip("\n") + "\n\n## 版本演进记录\n\n| 版本 | 日期 | 变更 | 来源 |\n|---|---|---|---|\n" + row + "\n"
    lines = prd_text.split("\n")
    start = prd_text[:m.start()].count("\n")
    i = start + 1
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    while i < len(lines) and lines[i].startswith("|"):
        i += 1
    lines.insert(i, row)
    return "\n".join(lines)


def _append_pending(prd_text: str, version: int, requirement: str) -> str:
    block = f"\n### V{version}（{_today()}，待消化）\n\n{requirement.strip()}\n"
    if PENDING_HEADING in prd_text:
        return prd_text.rstrip("\n") + "\n" + block
    return prd_text.rstrip("\n") + f"\n\n{PENDING_HEADING}\n" + block


def pending_versions(prd_text: str) -> list[str]:
    """「新增需求（待消化）」一节里还留着哪些版本块（### V2（…，待消化））。空列表表示都消化了。"""
    if PENDING_HEADING not in prd_text:
        return []
    section = prd_text.split(PENDING_HEADING, 1)[1]
    nxt = re.search(r"^## ", section, re.M)
    if nxt:
        section = section[:nxt.start()]
    return re.findall(r"^### (V\d+)（", section, re.M)


ANSWERS_HEADING = "## 6. 待确认问题与回答"


def record_answers(ws: Path, answers: list[tuple[str, str]], source: str = "网页界面") -> str:
    """把用户对待确认问题的回答写进 PRD 第 6 节末尾（下一节之前），并记一条迭代记录。不升版：回答是补全，不是新需求。"""
    ws = Path(ws)
    answers = [(q.strip(), a.strip()) for q, a in answers if q.strip() and a.strip()]
    if not answers:
        raise ValueError("没有可保存的回答")
    text = read_prd(ws)
    lines = [f"### 回答（{_today()}，{source}）", ""]
    for q, a in answers:
        lines += [f"- **问**：{_one_line(q)}", f"  **答**：{_one_line(a)}"]
    block = "\n".join(lines) + "\n"
    m = re.search(rf"^{re.escape(ANSWERS_HEADING)}\s*$", text, re.M)
    if not m:
        text = text.rstrip("\n") + f"\n\n{ANSWERS_HEADING}\n\n{block}"
    else:
        nxt = re.search(r"^## ", text[m.end():], re.M)
        cut = m.end() + nxt.start() if nxt else len(text)
        text = text[:cut].rstrip("\n") + "\n\n" + block + "\n" + text[cut:]
    atomic_write(ws / PRD_NAME, text)
    append_log(ws, f"V{current_version(text)} · 回答待确认问题", [
        f"回答了 {len(answers)} 个问题，已写进 PRD.md 第 6 节",
        "下一步：按补全后的 PRD 重新推导方案",
    ])
    return text


def _one_line(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text)


def bump_prd(ws: Path, requirement: str, source: str = "验证后的新需求") -> tuple[int, int, str]:
    """快照当前 PRD → prd/V{n}.md，升版到 V{n+1}，把新需求追加到待消化节。返回 (旧版本, 新版本, 新文本)。"""
    ws = Path(ws)
    text = read_prd(ws)
    old = current_version(text)
    new = old + 1
    snapshot = ws / HISTORY_DIR / f"V{old}.md"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        atomic_write(snapshot, text)
    plan = ws / "plan.json"
    plan_snapshot = ws / HISTORY_DIR / f"V{old}.plan.json"
    if plan.is_file() and not plan_snapshot.exists():      # 当时的方案也留一份，版本历史里能对比选型
        atomic_write(plan_snapshot, plan.read_text(encoding="utf-8"))
    summary = requirement.strip().splitlines()[0][:60]
    text = _bump_header(text, new)
    text = _append_history_row(text, f"| V{new} | {_today()} | {summary} | {source} |")
    text = _append_pending(text, new, requirement)
    atomic_write(ws / PRD_NAME, text)
    return old, new, text


# ---------------------------------------------------------------------------
# 选型对比与迭代记录
# ---------------------------------------------------------------------------

def load_components(ws: Path) -> dict[str, str]:
    path = Path(ws) / "plan.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {c["id"]: c["decision"] for c in data.get("components", []) if "id" in c}


def component_diff(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str, str]]:
    return [(cid, before.get(cid, "（无）"), after[cid]) for cid in sorted(after) if before.get(cid) != after[cid]]


def append_log(ws: Path, title: str, lines: list[str]) -> None:
    path = Path(ws) / LOG_NAME
    head = path.read_text(encoding="utf-8") if path.exists() else f"# 迭代记录 —— {Path(ws).name}\n"
    body = "\n".join(f"- {line}" for line in lines)
    atomic_write(path, head.rstrip("\n") + f"\n\n## {_today()} · {title}\n\n{body}\n")


def log_plan(out_dir: Path, plan, doc: Path) -> None:
    """输出目录如果是产品工作区（有 PRD.md 和 迭代记录.md），把这次推导记一条，保持循环记录完整。"""
    out_dir = Path(out_dir)
    if not ((out_dir / PRD_NAME).is_file() and (out_dir / LOG_NAME).is_file()):
        return
    version = current_version(read_prd(out_dir))
    must = [c["id"] for c in plan.components if c["decision"] == "必选"]
    append_log(out_dir, f"V{version} · 方案推导", [
        f"方案：{Path(doc).name}（模型 {plan.model_label}，审稿{'通过' if plan.review.get('ok') else '未完全通过，见文末意见'}）",
        f"必选组件：{'、'.join(must)}",
        f"待确认：{pending_summary(plan) or '无'}，见 方案.md 开头；回答写进 PRD.md 第 6 节",
        "人工验证结论：（待填）",
    ])


# ---------------------------------------------------------------------------
# revise / verify
# ---------------------------------------------------------------------------

def quick_reselect(prd_text: str, runner, ws: Path, log: Callable[[str], None] = print,
                   feature_overrides: dict[str, dict] | None = None) -> tuple[dict, list[dict]]:
    """只跑需求拆解（含特征多数票）+ 规则选型，不做架构设计与审稿。

    与 run_plan 用同一份 context 与提示词，所以结果进缓存后，之后的 `plan --resume` 会直接沿用需求拆解。
    不改写 plan.json / 方案.md（它们仍是上一版的设计）。
    """
    from blueprint.forward import _fmt_fact_keys, _fmt_features, _fmt_questions, vote_on_features
    from blueprint.knowledge import load_prompt
    from blueprint.pipeline import StageRunner
    from blueprint.rules import select_components
    from blueprint.schema import EXTRACT_SCHEMA, FEATURE_IDS
    prd_text = derivation_text(prd_text)        # 与 run_plan 同口径，缓存才能互通
    stages = StageRunner(runner, ws, resume=True, log=log, context={"kind": "plan", "input": prd_text})
    stages.save("input.md", prd_text)
    extract = stages.run("extract", load_prompt("extract").format(
        fact_keys=_fmt_fact_keys(), features=_fmt_features(),
        questions=_fmt_questions(), input=prd_text), EXTRACT_SCHEMA, "① 需求拆解（快速模式）")
    if set(feature_overrides or {}) < set(FEATURE_IDS):     # 和 run_plan 一致，缓存才能互通
        extract = {**extract, "features": vote_on_features(extract.get("features", {}), prd_text, stages, log)}
    if feature_overrides:
        extract = {**extract, "features": {**extract.get("features", {}), **feature_overrides}}
    log("  ▶ ③ 组件选型（规则，快速模式）")
    decisions = [d.to_dict() for d in select_components(extract.get("features", {}))]
    stages.save_json("stages/select.json", {"components": decisions})
    return extract, decisions


def revise_workspace(ws: Path, requirement: str, runner=None, run_plan_flag: bool = True,
                     log: Callable[[str], None] = print, quick: bool = False,
                     warn_undigested: bool = True, source: str = "验证后的新需求", stabilize: bool = True) -> dict:
    """warn_undigested=False 用于网页界面：那里的用户没有 AI 编程工具去「消化」新需求，
    新需求留在 PRD 第 7 节、由推导直接读取，就不在迭代记录里反复提醒。"""
    ws = Path(ws)
    if not requirement.strip():
        raise ValueError("新需求不能为空")
    before = load_components(ws)
    undigested = pending_versions(read_prd(ws))
    old, new, prd_text = bump_prd(ws, requirement, source=source)
    log(f"PRD 已从 V{old} 升到 V{new}，旧版快照：{ws / HISTORY_DIR / f'V{old}.md'}")

    result = {"old_version": old, "new_version": new, "diff": [], "unknowns": 0, "doc": None,
              "undigested": undigested}
    lines = [f"新需求：{requirement.strip().splitlines()[0][:120]}",
             f"PRD：V{old} → V{new}，新需求已追加到「{PENDING_HEADING[3:]}」，等 AI 消化进各节"]
    if undigested and warn_undigested:
        warn = f"⚠️ 上一轮的新需求还没消化：{'、'.join(undigested)} 仍留在「{PENDING_HEADING[3:]}」。先让 AI 把它们合并进 PRD 各节并更新 skeleton/，再继续叠加。"
        log(warn)
        lines.append(warn)
    overrides: dict[str, dict] = {}
    if run_plan_flag and runner is not None and stabilize and before:
        from blueprint.knowledge import COMPONENT_BY_ID, FEATURE_BY_ID
        from blueprint.stability import stable_overrides
        overrides, affected = stable_overrides(requirement, ws, runner, old, log=log)
        touched = sorted({FEATURE_BY_ID[f].component for f in affected})
        lines.append("重新判断：" + ("、".join(f"{c} {COMPONENT_BY_ID[c].name}" for c in touched) if touched else "无")
                     + f"；其余沿用 V{old} 的判断")
    if run_plan_flag and quick:
        if runner is None:
            raise ValueError("快速重选需要 runner；或加 --no-plan 只升版 PRD")
        extract, decisions = quick_reselect(prd_text, runner, ws, log=log, feature_overrides=overrides)
        after = {c["id"]: c["decision"] for c in decisions}
        diff = component_diff(before, after)
        result.update(diff=diff, unknowns=len(extract.get("unknowns", [])))
        lines.append("快速模式：只重跑了需求拆解与选型，方案.md 仍是上一版；选型有变化或要更新工具清单时运行 "
                     f"`blueprint plan out/{ws.name}/PRD.md -o out/{ws.name} --resume`（需求拆解已缓存，不重复计费）")
        if diff:
            lines.append("选型变化：" + "；".join(f"{cid} {a} → {b}" for cid, a, b in diff))
            todo = [f"按 {cid}_*/README.md 补 {cid}" for cid, _a, b in diff if b == "必选"]
            if todo:
                lines.append("骨架待办：" + "；".join(todo))
        else:
            lines.append("选型变化：无（新需求没有改变组件选型，只需在 skeleton/ 内改工具或提示词）")
        lines.append(f"待确认：{result['unknowns']} 条，见 stages/extract.json 的 unknowns；回答写进 PRD.md 第 6 节")
    elif run_plan_flag:
        if runner is None:
            raise ValueError("重推方案需要 runner；或加 --no-plan 只升版 PRD")
        from blueprint.forward import run_plan
        plan, doc = run_plan(prd_text, runner, ws, resume=True, log=log, feature_overrides=overrides)
        after = {c["id"]: c["decision"] for c in plan.components}
        diff = component_diff(before, after)
        result.update(diff=diff, unknowns=len(plan.extract.get("unknowns", [])), doc=doc)
        if diff:
            lines.append("选型变化：" + "；".join(f"{cid} {a} → {b}" for cid, a, b in diff))
            todo = [f"按 {cid}_*/README.md 补 {cid}" for cid, _a, b in diff if b == "必选"]
            if todo:
                lines.append("骨架待办：" + "；".join(todo))
        else:
            lines.append("选型变化：无（新需求没有改变组件选型，只需在 skeleton/ 内改工具或提示词）")
        lines.append(f"待确认：{pending_summary(plan) or '无'}，见 方案.md 开头；回答写进 PRD.md 第 6 节")
    else:
        lines.append("本轮未重推方案（--no-plan）；需要时运行 "
                     f"`blueprint plan out/{ws.name}/PRD.md -o out/{ws.name} --resume`")
    lines.append("人工验证结论：（待填）")
    append_log(ws, f"V{new} · 新需求", lines)
    return result


def verify_workspace(ws: Path, runner, log: Callable[[str], None] = print, fast: bool = False):
    ws = Path(ws)
    prd_text = read_prd(ws)
    skeleton = ws / SKELETON_DIR
    code_files = [p for p in skeleton.rglob("*") if p.is_file() and p.name != "README.md"
                  and ".venv" not in p.parts] if skeleton.is_dir() else []
    if not code_files:
        raise ValueError(f"{skeleton} 里还没有代码，先让 AI 按 方案.md 生成骨架再验证。")
    from blueprint.reverse import run_audit
    audit, doc = run_audit(skeleton, runner, ws / VERIFY_DIR, prd_text=derivation_text(prd_text), resume=False,
                           log=log, fast=fast)
    p0 = [f"{g.id} {g.name}" for g in audit.gaps if g.priority == "P0"]
    lines = [f"对照 PRD V{current_version(prd_text)} 检查 skeleton/：必选组件信号覆盖率 {int(audit.completion * 100)}%",
             f"报告：{doc}"]
    if p0:
        lines.append("P0 缺口：" + "、".join(p0))
    undigested = pending_versions(prd_text)
    if undigested:
        warn = f"⚠️ PRD 里 {'、'.join(undigested)} 的新需求还没消化进各节，这次验证对照的是旧需求；先消化再验证才算数。"
        log(warn)
        lines.append(warn)
    lines.append("人工验证结论：（待填：实际跑起来了吗？核心闭环走通了吗？新的想法写成下一轮 revise）")
    append_log(ws, f"V{current_version(prd_text)} · 验证", lines)
    return audit, doc


# ---------------------------------------------------------------------------
# 读：版本表与迭代记录（网页界面的「版本历史」用）
# ---------------------------------------------------------------------------

def version_table(prd_text: str) -> list[dict]:
    """PRD「版本演进记录」表格 → [{version, date, change, source}]，按版本升序。"""
    m = re.search(r"^## 版本演进记录\s*$", prd_text, re.M)
    if not m:
        return []
    rows = []
    for line in prd_text[m.end():].splitlines():
        if line.startswith("## "):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.fullmatch(r"V\d+", cells[0]):
            rows.append({"version": int(cells[0][1:]), "date": cells[1], "change": cells[2], "source": cells[3]})
    return sorted(rows, key=lambda r: r["version"])


def log_entries(ws: Path) -> list[dict]:
    """迭代记录.md → [{date, version, title, lines}]，按记录顺序。标题形如「2026-10-26 · V2 · 新需求」。"""
    path = Path(ws) / LOG_NAME
    if not path.is_file():
        return []
    entries = []
    for block in re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        parts = [p.strip() for p in head.split("·")]
        version = next((int(p[1:]) for p in parts if re.fullmatch(r"V\d+", p)), None)
        entries.append({
            "date": parts[0] if parts else "",
            "version": version,
            "title": parts[-1] if len(parts) > 1 else head.strip(),
            "lines": [ln[2:].strip() for ln in body.splitlines() if ln.startswith("- ")],
        })
    return entries
