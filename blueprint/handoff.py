"""交接包：把一个产品的需求、方案和选中组件的参考实现打成一个 zip，交给会写代码的人或他们的 AI 编程工具。

提出想法的人不懂技术，第一期的终点就是这个包。内容全部来自工作区已有的文件，不调模型。

    <产品名>-交接包/
    ├── 交接说明.md              从这里开始：一句话定位、第一版要做什么、还没定下来的事、怎么开始
    ├── 给AI编程工具的提示词.md   复制给 Claude Code / Cursor 等工具的一段话
    ├── PRD.md、方案.md、plan.json、迭代记录.md、prd/V*.md
    ├── skeleton/                已有的代码骨架（如果有）
    └── 参考组件/                第一版必选组件的说明与可运行的最小实现，外加它们共用的 common/
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

from blueprint.knowledge import COMPONENT_BY_ID
from blueprint.plain import plain_questions
from blueprint.workspace import LOG_NAME, PRD_NAME, SKELETON_DIR, current_version, read_prd

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/hubooooooo/agent-workshop"
_SKIP_PARTS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}
_SKIP_NAMES = {".env", ".DS_Store"}

AI_PROMPT = """这个文件夹是一个 Agent 产品的交接包。提出想法的人不懂技术，需求和方案都在这里，请你帮忙把它做出来。请按顺序：

1. 先读 交接说明.md、PRD.md、方案.md，用几句话复述你对这个产品的理解。
2. 交接说明.md 里「需要找提出想法的人确认」的问题，先列出来问我，不要自己替我决定；「技术待定项」由你判断，并说明理由。
3. 按 方案.md 的组件选型、工具清单和系统提示词草案，把可运行的代码骨架写进 skeleton/：自带 README.md、requirements.txt、.env.example，模型的 Key 从环境变量读，不要写进代码。
4. 选中的组件参考 参考组件/ 下的同名目录：README.md 讲原理和生产级要点，code.py 是可运行的最小实现。按这个产品的需要改写，不要整份照抄。
5. 每完成一部分，告诉我怎么运行、怎么验证它做对了。
"""


def _product_name(prd: str, fallback: str) -> str:
    for line in prd.splitlines():
        if line.replace(" ", "").startswith("|产品名|"):
            return line.split("|")[2].strip() or fallback
    return fallback


def _load_plan(ws: Path) -> dict:
    path = ws / "plan.json"
    if not path.is_file():
        raise ValueError("还没有方案，先生成方案再导出交接包。")
    return json.loads(path.read_text(encoding="utf-8"))


def handoff_filename(ws: Path) -> str:
    prd = read_prd(ws)
    return f"{_product_name(prd, ws.name)}-交接包-V{current_version(prd)}.zip"


def render_guide(ws: Path, plan: dict) -> str:
    prd = read_prd(ws)
    name = _product_name(prd, ws.name)
    users, devs = plain_questions(plan, ws)
    comps = plan.get("components", [])
    by = {d: [c for c in comps if c.get("decision") == d] for d in ("必选", "二期", "待确认", "放弃")}
    review = plan.get("review", {})
    out: list[str] = []
    w = out.append

    w(f"# {name} · 交接说明")
    w("")
    w(f"> 需求版本 V{current_version(prd)} · 导出于 {time.strftime('%Y-%m-%d')} · 由 [Agent 工坊]({REPO_URL}) 生成")
    w(">")
    w("> 提出这个想法的人不懂技术。需求和方案都在这个包里，请你（或你的 AI 编程工具）按方案把它做出来。")
    w("")
    w("## 一句话")
    w("")
    w(plan.get("one_liner") or plan.get("title") or name)
    w("")
    w("## 包里有什么")
    w("")
    w("| 文件 | 内容 |")
    w("|---|---|")
    w("| `PRD.md` | 需求文档，第 6 节是提出想法的人已经回答过的问题 |")
    w("| `方案.md` | 组件选型及理由、七层架构、工具清单、系统提示词草案、独立审稿意见 |")
    w("| `plan.json` | 方案的结构化版本 |")
    w("| `迭代记录.md`、`prd/` | 每一轮需求变化的记录与历史版本 |")
    w("| `参考组件/` | 第一版必选组件的说明和可运行的最小实现 |")
    w("| `给AI编程工具的提示词.md` | 交给 Claude Code、Cursor 等工具的一段话 |")
    w("")
    w("## 第一版要做的组件")
    w("")
    w("| 组件 | 为什么要做 | 参考 |")
    w("|---|---|---|")
    for c in by["必选"]:
        meta = COMPONENT_BY_ID.get(c["id"])
        folder = Path(meta.readme).parent.name if meta else ""
        w(f"| {c['id']} {c['name']} | {_cell(c.get('reason'))} | `参考组件/{folder}/` |")
    w("")
    if by["二期"]:
        w("以后再做：" + "、".join(f"{c['id']} {c['name']}" for c in by["二期"]) + "。第一版不用做，但留好扩展的位置。")
        w("")
    if by["待确认"]:
        w("取决于下面问题的回答：" + "、".join(f"{c['id']} {c['name']}" for c in by["待确认"]) + "。")
        w("")
    w("## 还没定下来的事")
    w("")
    w(f"### 需要找提出想法的人确认（{len(users)}）")
    w("")
    if users:
        w("这些问题提出想法的人还没回答。动手前先问清楚，答不上来的就是风险点。")
        w("")
        for i, q in enumerate(users, 1):
            w(f"{i}. {q['text']}")
    else:
        w("没有了。")
    w("")
    w(f"### 技术待定项（{len(devs)}，需要你判断）")
    w("")
    if devs:
        for i, q in enumerate(devs, 1):
            w(f"{i}. {q['original']}")
    else:
        w("没有了。")
    w("")
    if review.get("issues"):
        verdict = "通过" if review.get("ok") else "未通过"
        w(f"### 独立审稿意见（{verdict}，共 {len(review['issues'])} 条，详见 方案.md 文末）")
        w("")
        for i in review["issues"]:
            w(f"- [{i.get('severity', '')}] {i.get('section', '')}：{_cell(i.get('problem'))}")
        w("")
    w("## 怎么开始")
    w("")
    w("把 `给AI编程工具的提示词.md` 里的话交给你的 AI 编程工具，或者自己按同样的顺序来：")
    w("")
    w("```text")
    w(AI_PROMPT.strip())
    w("```")
    w("")
    w(f"参考组件来自 Agent 工坊（MIT 许可），完整仓库与其余组件见 {REPO_URL} 。")
    w("")
    return "\n".join(out)


def _cell(text) -> str:
    return str(text or "").replace("|", "／").replace("\n", " ").strip()


def _workspace_files(ws: Path) -> list[tuple[Path, str]]:
    files = [(ws / PRD_NAME, PRD_NAME), (ws / "方案.md", "方案.md"), (ws / "plan.json", "plan.json"),
             (ws / LOG_NAME, LOG_NAME)]
    files += [(p, f"prd/{p.name}") for p in sorted((ws / "prd").glob("V*.md"))]
    files += [(p, f"verify/{p.name}") for p in sorted((ws / "verify").glob("*.md"))]
    skeleton = ws / SKELETON_DIR
    if skeleton.is_dir():
        for p in sorted(skeleton.rglob("*")):
            rel = p.relative_to(skeleton)
            if p.is_file() and not p.is_symlink() and not (_SKIP_PARTS & set(rel.parts)) and p.name not in _SKIP_NAMES:
                files.append((p, f"skeleton/{rel.as_posix()}"))
    return [(p, arc) for p, arc in files if p.is_file()]


# 参考实现之间的运行时依赖（code.py 里按路径加载别的组件）。tests/test_handoff.py 扫描源码守护这张表不漏。
REFERENCE_DEPS = {"s15": ("s09",), "s16": ("s15",)}


def reference_components(plan: dict) -> list[str]:
    """第一版必选的组件，加上它们的参考实现运行时要用到的组件。"""
    chosen = [c["id"] for c in plan.get("components", []) if c.get("decision") == "必选"]
    seen: list[str] = []
    stack = list(reversed(chosen))
    while stack:
        cid = stack.pop()
        if cid in seen or cid not in COMPONENT_BY_ID:
            continue
        seen.append(cid)
        stack.extend(REFERENCE_DEPS.get(cid, ()))
    return sorted(seen)


def _reference_files(plan: dict) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for cid in reference_components(plan):
        folder = ROOT / Path(COMPONENT_BY_ID[cid].readme).parent
        for pattern in ("README.md", "code.py", "images/*.svg", "*_parts/*.py"):
            for p in sorted(folder.glob(pattern)):
                files.append((p, f"参考组件/{p.relative_to(ROOT).as_posix()}"))
    if files:
        files += [(ROOT / "common" / "__init__.py", "参考组件/common/__init__.py"),
                  (ROOT / "common" / "bootstrap.py", "参考组件/common/bootstrap.py"),
                  (ROOT / "LICENSE", "参考组件/LICENSE")]
    return [(p, arc) for p, arc in files if p.is_file()]


REFERENCE_README = """# 参考组件

来自 Agent 工坊（MIT 许可，见 LICENSE），只包含这个产品第一版必选的组件。

- 每个目录的 README.md 讲这个机制解决什么问题、生产级要注意什么；code.py 是可运行的最小实现。
- 个别组件的参考实现会用到别的组件（比如 s15 会加载 s09），这些也一并放进来了，不代表第一版要做。
- 运行方式：在本目录（参考组件/）下执行 `python sNN_xxx/code.py`。需要 `pip install anthropic python-dotenv`，
  并在环境变量或 .env 里配置 ANTHROPIC_API_KEY（用 DeepSeek 等兼容服务时再配 ANTHROPIC_BASE_URL 和 MODEL_ID）。
- 它们是教学用的参考实现，按产品需要改写，不要整份照抄进产品代码。
"""


def build_handoff(ws: Path) -> bytes:
    ws = Path(ws)
    plan = _load_plan(ws)
    prd = read_prd(ws)
    top = f"{_product_name(prd, ws.name)}-交接包/"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(top + "交接说明.md", render_guide(ws, plan))
        z.writestr(top + "给AI编程工具的提示词.md", AI_PROMPT)
        for path, arc in _workspace_files(ws):
            z.write(path, top + arc)
        refs = _reference_files(plan)
        if refs:
            z.writestr(top + "参考组件/README.md", REFERENCE_README)
        for path, arc in refs:
            z.write(path, top + arc)
    return buf.getvalue()
