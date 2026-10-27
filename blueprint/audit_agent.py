"""反向检查的 agent：自己翻项目代码，反推意图，逐个核实组件，交出带代码证据的结论。

工具全部只读、只在被检查的项目目录内，没有写入或执行命令的能力；密钥类文件一律不读，
避免把别人的密钥发给模型服务商。扫描器（scanner.py）的结果只作为线索给它。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from blueprint.agent import Tool, run_agent
from blueprint.forward import _fmt_fact_keys, _fmt_features, _dump
from blueprint.knowledge import COMPONENT_BY_ID, COMPONENTS, load_prompt
from blueprint.pipeline import SYSTEM
from blueprint.rules import select_components
from blueprint.scanner import EXCLUDE_DIRS, TEXT_EXT, Inventory, _iter_files
from blueprint.schema import EXTRACT_SCHEMA, coerce_stage_output

ROOT = Path(__file__).resolve().parent.parent
MAX_TURNS = 30
READ_LINES = 300
MAX_READ_BYTES = 200_000
MAX_SEARCH_HITS = 50
MAX_LIST_ENTRIES = 200
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}
SECRET_NAMES = {".env", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json"}

_FINDING = {
    "type": "object",
    "required": ["strength", "evidence"],
    "properties": {
        "strength": {"type": "string", "enum": ["strong", "weak", "none"]},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["file", "line", "note"],
                "properties": {
                    "file": {"type": "string", "minLength": 1},
                    "line": {"type": "integer", "minimum": 1},
                    "note": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}

RESULT_SCHEMA = {
    "type": "object",
    "required": ["intent", "components"],
    "properties": {
        "intent": EXTRACT_SCHEMA,
        "components": {"type": "object", "additionalProperties": _FINDING},
    },
}


def is_secret(rel: Path) -> bool:
    name = rel.name.lower()
    if name == ".env.example":
        return False
    return name in SECRET_NAMES or name.startswith(".env.") or rel.suffix.lower() in SECRET_SUFFIXES


class ProjectFiles:
    """被检查项目的只读视图：所有路径都要过 resolve()，并记下读过、搜到过哪些文件。"""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.seen: dict[str, int] = {}          # 相对路径 -> 总行数

    def resolve(self, path: str) -> Path:
        raw = str(path or ".").strip()
        target = (self.root / raw).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise ValueError(f"拒绝：{raw} 不在被检查的项目目录内")
        rel = target.relative_to(self.root)
        for part in rel.parts:
            if part in EXCLUDE_DIRS or (part.startswith(".") and part not in (".github", ".env.example")):
                raise ValueError(f"拒绝：{raw} 在忽略目录或隐藏路径里")
        if is_secret(rel):
            raise ValueError(f"拒绝：{raw} 可能含密钥，不读取")
        if not target.exists():
            raise ValueError(f"{raw} 不存在")
        return target

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def _text(self, target: Path) -> list[str]:
        if target.stat().st_size > MAX_READ_BYTES:
            raise ValueError(f"{self.rel(target)} 超过 {MAX_READ_BYTES // 1000} KB，不读取；可以用 search 找关键行")
        data = target.read_bytes()
        if b"\0" in data[:4096]:
            raise ValueError(f"{self.rel(target)} 是二进制文件")
        return data.decode("utf-8", errors="replace").splitlines()

    def list_dir(self, args: dict) -> str:
        base = self.resolve(args.get("path", "."))
        if not base.is_dir():
            raise ValueError(f"{self.rel(base)} 不是目录")
        depth = min(int(args.get("depth", 2) or 2), 3)
        lines: list[str] = []

        def walk(d: Path, level: int) -> None:
            for entry in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
                if len(lines) >= MAX_LIST_ENTRIES:
                    return
                if entry.is_symlink() or entry.name in EXCLUDE_DIRS:
                    continue
                if entry.name.startswith(".") and entry.name not in (".github", ".env.example"):
                    continue
                if entry.is_dir():
                    lines.append("  " * level + entry.name + "/")
                    if level + 1 < depth:
                        walk(entry, level + 1)
                else:
                    lines.append("  " * level + f"{entry.name}  ({entry.stat().st_size} B)")

        walk(base, 0)
        if len(lines) >= MAX_LIST_ENTRIES:
            lines.append(f"……只列出前 {MAX_LIST_ENTRIES} 项")
        return "\n".join(lines) or "（空目录）"

    def read_file(self, args: dict) -> str:
        target = self.resolve(args.get("path", ""))
        if not target.is_file():
            raise ValueError(f"{self.rel(target)} 不是文件")
        lines = self._text(target)
        start = max(int(args.get("start_line", 1) or 1), 1)
        end = min(int(args.get("end_line", start + READ_LINES - 1) or start + READ_LINES - 1),
                  start + READ_LINES - 1, len(lines))
        self.seen[self.rel(target)] = len(lines)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n……共 {len(lines)} 行，用 start_line={end + 1} 继续读" if end < len(lines) else ""
        return f"{self.rel(target)}（第 {start}-{end} 行，共 {len(lines)} 行）\n{body}{more}"

    def search(self, args: dict) -> str:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern 不能为空")
        try:
            regex = re.compile(pattern, re.I)
        except re.error:
            regex = re.compile(re.escape(pattern), re.I)
        base = self.resolve(args.get("path", "."))
        files = [base] if base.is_file() else list(_iter_files(base))
        hits: list[str] = []
        for path in files:
            rel = path.relative_to(self.root)
            if path.suffix not in TEXT_EXT or is_secret(rel):
                continue
            try:
                lines = self._text(path)
            except (OSError, ValueError):
                continue
            matched = False
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    matched = True
                    hits.append(f"{rel.as_posix()}:{i}: {line.strip()[:160]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
            if matched:
                self.seen[rel.as_posix()] = len(lines)
            if len(hits) >= MAX_SEARCH_HITS:
                hits.append(f"……命中超过 {MAX_SEARCH_HITS} 处，请缩小范围")
                break
        return "\n".join(hits) or "没有命中"


def component_card(args: dict) -> str:
    comp = COMPONENT_BY_ID.get(str(args.get("id", "")).strip().lower())
    if comp is None:
        raise ValueError("没有这个组件编号，可用：" + "、".join(c.id for c in COMPONENTS))
    readme = (ROOT / comp.readme)
    excerpt = readme.read_text(encoding="utf-8")[:1500] if readme.is_file() else ""
    return (f"{comp.id} {comp.name}（{comp.domain}）：{comp.one_liner}\n"
            f"什么时候需要：{comp.when}\n生产级要点：{comp.production_points}\n"
            f"扫描器用的关键词（只是线索，命中不代表实现）：{', '.join(comp.signals)}\n\n参考实现说明节选：\n{excerpt}")


def select_tool(args: dict) -> str:
    features = coerce_stage_output("infer", {"features": args.get("features", {})})["features"]
    lines = [f"{d.id} {d.name}：{d.decision}（{d.reason}）" for d in select_components(features)]
    return "按规则算出的组件选型（交卷后会按你最终交的 features 重算一次）：\n" + "\n".join(lines)


def expected_ids(features: dict) -> list[str]:
    return [d.id for d in select_components(features) if d.decision != "放弃"]


def _norm(path: str) -> str:
    path = path.strip().replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def make_check(files: ProjectFiles, required: Callable[[dict], list[str]]) -> Callable[[dict], list[str]]:
    """schema 之外的交卷校验：该核实的组件都有结论，证据文件真读过、行号真存在。"""
    def check(result: dict) -> list[str]:
        errors: list[str] = []
        findings = result["components"]
        for cid in findings:
            if cid not in COMPONENT_BY_ID:
                errors.append(f"components.{cid}: 不是组件编号，应为 s01–s17")
        for cid in required(result):
            if cid not in findings:
                errors.append(f"components.{cid}: 它是必选/二期/待确认，或扫描器判为有，必须给出结论")
        for cid, f in findings.items():
            if f["strength"] != "none" and not f["evidence"]:
                errors.append(f"components.{cid}: 判 {f['strength']} 至少要有一条代码证据")
            for ev in f["evidence"]:
                path = _norm(ev["file"])
                if path not in files.seen:
                    errors.append(f"components.{cid}: 证据文件 {ev['file']} 你没有读过或搜到过，先用 read_file 核实")
                elif ev["line"] > files.seen[path]:
                    errors.append(f"components.{cid}: {ev['file']} 只有 {files.seen[path]} 行，第 {ev['line']} 行不存在")
        return errors
    return check


def _describe(name: str, args: dict) -> str:
    if name == "read_file":
        start = args.get("start_line")
        return f"读 {args.get('path', '')}" + (f"（从第 {start} 行）" if start and start != 1 else "")
    if name == "list_dir":
        return f"看目录 {args.get('path', '.') or '.'}"
    if name == "search":
        return f"搜索 {args.get('pattern', '')}" + (f"（在 {args['path']}）" if args.get("path") else "")
    if name == "component_card":
        return f"查组件说明 {args.get('id', '')}"
    if name == "select_components":
        return "按规则算组件选型"
    return name


def _tools(files: ProjectFiles, with_select: bool) -> list[Tool]:
    path_prop = {"type": "string", "description": "相对于项目根目录的路径，. 表示根目录"}
    tools = [
        Tool("list_dir", "列出目录内容（跳过 .git、node_modules 等）。", {
            "type": "object", "properties": {"path": path_prop,
                                             "depth": {"type": "integer", "description": "展开层数，1–3，默认 2"}}},
            files.list_dir),
        Tool("read_file", f"按行读取文本文件，带行号返回，一次最多 {READ_LINES} 行。", {
            "type": "object", "required": ["path"],
            "properties": {"path": path_prop, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}},
            files.read_file),
        Tool("search", f"在项目里按正则（不区分大小写）搜代码，返回「文件:行号: 内容」，最多 {MAX_SEARCH_HITS} 条。", {
            "type": "object", "required": ["pattern"],
            "properties": {"pattern": {"type": "string"}, "path": {**path_prop, "description": "只在这个目录或文件里搜，默认整个项目"}}},
            files.search),
        Tool("component_card", "查某个 Harness 组件（s01–s17）是什么、在代码里通常长什么样。", {
            "type": "object", "required": ["id"], "properties": {"id": {"type": "string", "description": "如 s03"}}},
            component_card),
    ]
    if with_select:
        tools.append(Tool("select_components", "传入你判断的 14 个特征，返回规则算出的组件选型，告诉你哪些组件需要核实。", {
            "type": "object", "required": ["features"],
            "properties": {"features": {"type": "object", "description": "{feature_id: {value, evidence}}"}}},
            select_tool))
    return tools


def investigate(project: Path, inventory: Inventory, runner, out_dir: Path, prd_decisions: list[dict] | None,
                log: Callable[[str], None] = print, max_turns: int = MAX_TURNS,
                resume: bool = False) -> tuple[dict, dict, dict]:
    """返回 (intent, findings, stats)。失败抛 AgentFailed 或模型调用异常，由调用方退回快速扫描。

    resume=True 且源码、PRD 选型、模型、提示词都没变时，沿用上次的结论，不再调模型。
    """
    cache = out_dir / "stages" / "audit_agent.json"
    signature = hashlib.sha256(json.dumps(
        [inventory.source_digest, prd_decisions, getattr(runner, "name", ""), getattr(runner, "model", ""),
         load_prompt("audit_agent")], ensure_ascii=False).encode()).hexdigest()
    if resume and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("signature") == signature:
                log("  ↻ agent 结论：沿用上次结果")
                return cached["intent"], cached["components"], cached["stats"]
        except (OSError, ValueError, KeyError):
            pass
    files = ProjectFiles(project)
    # 扫描器判为有 / 弱的组件也要 agent 确认或推翻，否则报告会沿用关键词误报
    flagged = [cid for cid, sig in inventory.components.items() if sig.strength != "none"]
    recheck = ("\n\n另外，扫描线索里 strength 不是 none 的组件也都要核实并交结论（确认或推翻扫描结果）："
               + "、".join(flagged) + "。没交结论的组件一律按 none 处理。") if flagged else ""
    if prd_decisions is not None:
        wanted = [d["id"] for d in prd_decisions if d["decision"] != "放弃"]

        def required(_result: dict) -> list[str]:
            return sorted(set(wanted) | set(flagged))

        expected = "\n".join(f"- {d['id']} {d['name']}：{d['decision']}" for d in prd_decisions)
        selection = ("## 这个项目应有的组件（已按用户提供的 PRD 用规则算好，不用你再判断）\n"
                     f"{expected}\n\n必选、二期、待确认的组件都要核实；放弃的可以不交。")
    else:
        def required(result: dict) -> list[str]:
            return sorted(set(expected_ids(coerce_stage_output("infer", result["intent"])["features"])) | set(flagged))

        selection = ("## 这个项目应有的组件\n先读代码判断 14 个特征，再调用 select_components 看规则算出的选型；"
                     "必选、二期、待确认的组件都要核实，放弃的可以不交。")
    prompt = load_prompt("audit_agent").format(
        fact_keys=_fmt_fact_keys(), features=_fmt_features(), selection=selection + recheck,
        readme=inventory.readme[:6000] or "（没有 README）", tree=inventory.tree,
        inventory_json=_dump(inventory.brief()), max_turns=max_turns)
    result = run_agent("audit_agent", SYSTEM, prompt, _tools(files, prd_decisions is None), RESULT_SCHEMA, runner,
                       log=log, max_turns=max_turns, describe=_describe,
                       check=make_check(files, required),
                       transcript=out_dir / "stages" / "audit_agent.transcript.jsonl",
                       last_turn_hint="调查轮数或费用已用完。请立即调用 finish，用已掌握的信息交卷；"
                                      "没核实到的组件判 weak 或 none，并在 note 里写明未核实。")
    intent = coerce_stage_output("infer", result["intent"])
    findings = {cid: {"strength": f["strength"],
                      "evidence": [{**ev, "file": _norm(ev["file"])} for ev in f["evidence"]]}
                for cid, f in result["components"].items() if cid in COMPONENT_BY_ID}
    stats = {"files_seen": len(files.seen)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"signature": signature, "intent": intent, "components": findings, "stats": stats},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    return intent, findings, stats

