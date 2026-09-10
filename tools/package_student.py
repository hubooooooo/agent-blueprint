"""按允许清单生成学生文件包，不收集本地环境、密钥或运行产物。"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "使用引导.md", "BLUEPRINT.md", "LICENSE",
    "requirements.txt", "setup.sh", ".env.example", ".gitignore",
    "启动引擎.command",
)
PATTERNS = (
    ".vscode/*.json",
    "docs/beginner-guide.md", "docs/prd-toy-theater.md",
    "docs/维护手册.md", "docs/requirements.md", "docs/examples/*.md",
    "blueprint/*.py", "blueprint/knowledge/*.py", "blueprint/knowledge/prompts/*.md",
    "s[0-9][0-9]_*/README.md", "s[0-9][0-9]_*/code.py", "s[0-9][0-9]_*/images/*.svg",
    "scaffold/*.py", "scaffold/*.md", "scaffold/*.yaml", "scaffold/requirements.txt", "scaffold/.env.example",
    "skills/*/SKILL.md", "skills/*/references/*.md", "skills/*/references/*.py", "skills/*/scripts/*.py",
    "evals/forward/*/input.md", "evals/forward/*/expected.json",
    "evals/reverse/*/expected.json", "evals/reverse/*/target.txt",
    "evals/reverse/*/README.md", "evals/reverse/*/src/*.py",
    "tests/test_*.py", "tools/package_student.py", "tools/wizard.py",
)


def collect_files(root: Path) -> list[Path]:
    selected = {root / name for name in ROOT_FILES}
    for pattern in PATTERNS:
        selected.update(root.glob(pattern))
    for path in selected:
        relative = path.relative_to(root)
        if not path.is_file():
            raise ValueError(f"缺少分发文件：{relative}")
        if any((root / Path(*relative.parts[:i])).is_symlink()
               for i in range(1, len(relative.parts) + 1)):
            raise ValueError(f"分发文件不能是符号链接：{relative}")
        if path.name == ".env.example":
            # 模板中只能包含占位 Key；不回显任何实际配置值。
            for line in path.read_text(encoding="utf-8").splitlines():
                name, sep, value = line.partition("=")
                if sep and name.strip() in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}:
                    if value.strip().strip('"\'') not in {"", "sk-ant-xxx"}:
                        raise ValueError(f"{relative} 含非占位凭证，请恢复模板再打包")
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def package(root: Path, output: Path) -> tuple[int, int]:
    files = collect_files(root)
    if output.resolve() in {path.resolve() for path in files}:
        raise ValueError("输出路径不能覆盖分发源文件")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".student-", suffix=".zip", dir=output.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                archive.write(path, "agent-blueprint/" + path.relative_to(root).as_posix())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(files), output.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", type=Path, default=ROOT / "dist/agent-blueprint-student.zip")
    args = parser.parse_args()
    try:
        count, size = package(ROOT, args.out)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"打包失败：{exc}\n")
    print(f"已生成：{args.out.resolve()}（{count} 个文件，{size / 1024:.1f} KiB）")


if __name__ == "__main__":
    main()
