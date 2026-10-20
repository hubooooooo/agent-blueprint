# s13_agent_teams / p04_base_tools.py —— 小节「Base Tools」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Base Tools --

def safe_path(p: str, cwd: Path | None = None) -> Path:
    base = (cwd or WORKDIR).resolve()
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        output = output[:50000] if output else "(no output)"
        if result.returncode:
            return f"Error: command exited with status {result.returncode}\n{output}"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except OSError as exc:
        return f"Error: {type(exc).__name__}: {exc}"


def run_read(path: str, limit: int | None = None,
             cwd: Path | None = None) -> str:
    try:
        lines = safe_path(path, cwd).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str, cwd: Path | None = None) -> str:
    try:
        fp = safe_path(path, cwd)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str,
             cwd: Path | None = None) -> str:
    try:
        target = safe_path(path, cwd)
        content = target.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count != 1:
            return f"Error: Expected 1 occurrence, found {count}"
        target.write_text(content.replace(old_text, new_text), encoding="utf-8")
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_glob(pattern: str, cwd: Path | None = None) -> str:
    try:
        base = (cwd or WORKDIR).resolve()
        matches = [
            str(path.relative_to(base))
            for path in sorted(base.glob(pattern))
            if path.resolve().is_relative_to(base)
        ]
        return "\n".join(matches[:200]) or "No files found"
    except Exception as exc:
        return f"Error: {exc}"


def _agent_cwd() -> tuple[Path | None, str | None]:
    try:
        return assignment_cwd("agent"), None
    except (FileNotFoundError, ValueError) as exc:
        return None, f"Error: Invalid task assignment: {exc}"


def run_agent_bash(command: str) -> str:
    cwd, error = _agent_cwd()
    return error or run_bash(command, cwd)


def run_agent_read(path: str, limit: int | None = None) -> str:
    cwd, error = _agent_cwd()
    return error or run_read(path, limit, cwd)


def run_agent_write(path: str, content: str) -> str:
    cwd, error = _agent_cwd()
    return error or run_write(path, content, cwd)


def run_agent_edit(path: str, old_text: str, new_text: str) -> str:
    cwd, error = _agent_cwd()
    return error or run_edit(path, old_text, new_text, cwd)


def run_agent_glob(pattern: str) -> str:
    cwd, error = _agent_cwd()
    return error or run_glob(pattern, cwd)
