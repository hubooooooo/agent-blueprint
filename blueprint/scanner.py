"""反向扫描器：不花钱的体力活。列目录、找依赖、找模型调用、按组件信号正则扫源码。"""

from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from blueprint.knowledge import ACCEPTANCE, COMPONENTS

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist",
                "build", "out", ".runtime", ".transcripts", ".task_outputs", ".worktrees", ".idea",
                ".vscode", "archive", ".mypy_cache", ".ruff_cache", "target", "vendor"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".kt", ".swift", ".sh"}
TEXT_EXT = CODE_EXT | {".md", ".yaml", ".yml", ".toml", ".json", ".txt", ".cfg", ".ini"}
MAX_FILE_BYTES = 400_000
MAX_HITS_PER_COMPONENT = 20

LLM_SDK_PATTERNS = {
    "anthropic": r"\bimport anthropic\b|\bfrom anthropic\b|@anthropic-ai/sdk|Anthropic\(",
    "openai": r"\bimport openai\b|\bfrom openai\b|from \"openai\"|OpenAI\(",
    "google-genai": r"google\.generativeai|google-genai|@google/generative-ai",
    "langchain": r"\blangchain\b",
    "litellm": r"\blitellm\b",
    "ollama": r"\bollama\b",
}

ACCEPTANCE_PATTERNS = {
    "runnable": [r"if __name__ == .__main__.", r"def main\(", r"\"scripts\"\s*:", r"argparse", r"click\.command", r"typer"],
    "fault_tolerant": [r"\bretry\b", r"\btimeout\b", r"backoff", r"fallback", r"except \w+Error", r"catch \("],
    "observable": [r"\blogging\b", r"logger\.", r"\bmetrics?\b", r"trajector", r"\.jsonl", r"opentelemetry", r"prometheus"],
    "testable": [r"^tests?/", r"test_\w+\.py$", r"\.test\.(ts|js)$", r"_test\.go$", r"pytest", r"\bjest\b"],
    "deployable": [r"^Dockerfile$", r"docker-compose", r"^Procfile$", r"^setup\.sh$", r"^Makefile$", r"\bdeploy", r"fly\.toml", r"vercel\.json"],
    "measurable": [r"成功率", r"准确率", r"完成率", r"\blatency\b", r"\bcost\b", r"\bkpi\b", r"success_rate", r"指标"],
}


@dataclass
class Hit:
    file: str
    line: int
    pattern: str
    text: str


@dataclass
class ComponentSignal:
    id: str
    strength: str = "none"       # none | weak | strong
    code_files: int = 0
    doc_files: int = 0
    hits: list[Hit] = field(default_factory=list)


@dataclass
class Inventory:
    root: str
    readme: str = ""
    tree: str = ""
    file_count: int = 0
    ext_counts: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    llm_sdks: dict = field(default_factory=dict)          # name -> [file:line]
    components: dict = field(default_factory=dict)        # id -> ComponentSignal
    acceptance: dict = field(default_factory=dict)        # key -> {"status", "evidence"}
    config_files: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    source_digest: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["components"] = {k: asdict(v) if not isinstance(v, dict) else v for k, v in self.components.items()}
        return d

    def brief(self) -> dict:
        """给模型看的精简版：不带全部命中行。"""
        return {
            "file_count": self.file_count,
            "ext_counts": self.ext_counts,
            "dependencies": self.dependencies[:40],
            "llm_sdks": {k: v[:3] for k, v in self.llm_sdks.items()},
            "config_files": self.config_files,
            "entry_points": self.entry_points[:10],
            "components": {k: {"strength": v.strength, "code_files": v.code_files,
                               "sample": [f"{h.file}:{h.line}" for h in v.hits[:3]]}
                           for k, v in self.components.items()},
            "acceptance": self.acceptance,
        }


def _iter_files(root: Path):
    # 真正剪枝，避免先遍历整个 node_modules / .venv 再过滤。
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS
                         and (not d.startswith(".") or d == ".github")
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if name.startswith(".") and name != ".env.example":
                continue
            if not path.is_symlink() and path.is_file():
                yield path


def _build_tree(root: Path, max_depth: int = 3, max_lines: int = 120) -> str:
    lines: list[str] = []

    def walk(dir_path: Path, depth: int):
        if depth > max_depth or len(lines) >= max_lines:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.name in EXCLUDE_DIRS or (entry.name.startswith(".") and entry.name not in (".env.example", ".github")):
                continue
            if len(lines) >= max_lines:
                lines.append("    " * depth + "…")
                return
            lines.append("    " * depth + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(root, 0)
    return "\n".join(lines)


def _read_deps(root: Path) -> list[str]:
    deps: list[str] = []
    req = root / "requirements.txt"
    if req.is_file() and not req.is_symlink():
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                deps.append(re.split(r"[=<>!~ ]", line)[0])
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
        if m:
            deps += re.findall(r"\"([A-Za-z0-9_.\-]+)", m.group(1))
    package = root / "package.json"
    if package.is_file() and not package.is_symlink():
        try:
            data = json.loads(package.read_text(encoding="utf-8", errors="replace"))
            for key in ("dependencies", "devDependencies"):
                deps += list((data.get(key) or {}).keys())
        except (ValueError, AttributeError, TypeError):
            pass
    return sorted(set(deps))


def scan_project(root: Path | str) -> Inventory:
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{root}")
    inv = Inventory(root=str(root))
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file() and not p.is_symlink():
            inv.readme = p.read_text(encoding="utf-8", errors="replace")[:12000]
            break
    inv.tree = _build_tree(root)
    inv.dependencies = _read_deps(root)

    signals = {c.id: ComponentSignal(c.id) for c in COMPONENTS}
    compiled = {c.id: [re.compile(p, re.I) for p in c.signals] for c in COMPONENTS}
    sdk_compiled = {k: re.compile(v) for k, v in LLM_SDK_PATTERNS.items()}
    acc_compiled = {k: [re.compile(p, re.I | re.M) for p in v] for k, v in ACCEPTANCE_PATTERNS.items()}
    acc_evidence: dict[str, list[str]] = {k: [] for k in ACCEPTANCE}
    comp_code_files: dict[str, set[str]] = {c.id: set() for c in COMPONENTS}
    comp_doc_files: dict[str, set[str]] = {c.id: set() for c in COMPONENTS}
    code_hits: dict[str, int] = {c.id: 0 for c in COMPONENTS}
    source_hash = hashlib.sha256()

    for path in _iter_files(root):
        rel = str(path.relative_to(root))
        inv.file_count += 1
        inv.ext_counts[path.suffix] = inv.ext_counts.get(path.suffix, 0) + 1
        if path.name in (".env.example", "config.yaml", "config.example.yaml", "config.toml", "settings.yaml", "pyproject.toml"):
            inv.config_files.append(rel)
        # 文件名级别的验收线索
        for key in ("testable", "deployable"):
            for pat in acc_compiled[key]:
                if pat.search(rel) and len(acc_evidence[key]) < 8:
                    acc_evidence[key].append(rel)
                    break
        if path.suffix not in TEXT_EXT:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_hash.update(json.dumps([rel, text], ensure_ascii=False).encode())
        is_code = (path.suffix in CODE_EXT
                   and not any(p in {"test", "tests", "evals", "__tests__"} for p in path.relative_to(root).parts)
                   and not re.search(r"(^test_|_test\.py$|\.test\.|\.spec\.|_test\.go$)", path.name))
        lines = text.splitlines()
        if is_code and re.search(r"if __name__ == .__main__.|def main\(|\"bin\"\s*:", text):
            inv.entry_points.append(rel)
        for sdk, pat in sdk_compiled.items():
            if not is_code:
                continue
            for i, line in enumerate(lines, 1):
                if pat.search(line):
                    inv.llm_sdks.setdefault(sdk, []).append(f"{rel}:{i}")
                    break
        for cid, pats in compiled.items():
            sig = signals[cid]
            matched = False
            for i, line in enumerate(lines, 1):
                for pat in pats:
                    if pat.search(line):
                        matched = True
                        if is_code:
                            code_hits[cid] += 1
                        if is_code and len(sig.hits) < MAX_HITS_PER_COMPONENT:
                            sig.hits.append(Hit(rel, i, pat.pattern, line.strip()[:120]))
                        break
            if matched:
                (comp_code_files if is_code else comp_doc_files)[cid].add(rel)
        for key in ("runnable", "fault_tolerant", "observable", "measurable"):
            if not is_code:
                continue
            if len(acc_evidence[key]) >= 8:
                continue
            for pat in acc_compiled[key]:
                m = pat.search(text)
                if m:
                    line_no = text.count("\n", 0, m.start()) + 1
                    acc_evidence[key].append(f"{rel}:{line_no}")
                    break

    for cid, sig in signals.items():
        sig.code_files = len(comp_code_files[cid])
        sig.doc_files = len(comp_doc_files[cid])
        if sig.code_files >= 2 or code_hits[cid] >= 4:
            sig.strength = "strong"
        elif sig.code_files >= 1:
            sig.strength = "weak"
        else:
            sig.strength = "none"
    inv.components = signals
    inv.source_digest = source_hash.hexdigest()

    # 验收六条
    has_readme = bool(inv.readme.strip())
    has_config = bool(inv.config_files)
    for key, (name, _desc) in ACCEPTANCE.items():
        ev = acc_evidence[key]
        if key == "runnable":
            ok = bool(inv.entry_points) and has_readme
            status = "pass" if ok and has_config else ("partial" if ok else "fail")
            ev = inv.entry_points[:3] + inv.config_files[:3]
        elif key == "deployable":
            status = "pass" if ev and has_readme else ("partial" if ev or has_readme else "fail")
        else:
            status = "pass" if len(ev) >= 2 else ("partial" if ev else "fail")
        inv.acceptance[key] = {"name": name, "status": status, "evidence": ev[:6]}
    return inv
