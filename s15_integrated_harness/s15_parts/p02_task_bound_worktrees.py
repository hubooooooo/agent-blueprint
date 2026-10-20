# s15_integrated_harness / p02_task_bound_worktrees.py —— 小节「Task-bound Worktrees」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Task-bound Worktrees --

WORKTREES_DIR = WORKDIR / ".worktrees"
WORKTREES_ROOT = WORKTREES_DIR.resolve()
VALID_WORKTREE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_worktree_name(name: str) -> str | None:
    if not isinstance(name, str) or not VALID_WORKTREE_NAME.fullmatch(name):
        return ("worktree name must be 1-64 letters, digits, dots, "
                "underscores, or dashes, and start with a letter or digit")
    if name in {".", ".."} or ".." in name:
        return "worktree name cannot contain '..'"
    return None


def _worktree_path(name: str) -> Path:
    path = (WORKTREES_DIR / name).resolve()
    if (not WORKTREES_ROOT.is_relative_to(WORKDIR.resolve())
            or not path.is_relative_to(WORKTREES_ROOT)
            or path == WORKTREES_ROOT):
        raise ValueError(f"Worktree path escapes directory: {name!r}")
    return path


def _worktree_branch(name: str) -> str:
    return f"wt/{name}"


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """Run Git without shell interpolation and return (ok, combined output)."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd or WORKDIR,
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output or "(no output)"


def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """Run Git and bound only the text returned to the model."""
    ok, output = _run_git(args, cwd)
    return ok, output[:5000]


def _registered_worktrees() -> tuple[dict[Path, dict[str, str]], str | None]:
    ok, output = _run_git(["worktree", "list", "--porcelain"])
    if not ok:
        return {}, f"cannot read Git worktree registry: {output}"
    entries: dict[Path, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in output.splitlines() + [""]:
        if not line:
            raw_path = current.get("worktree")
            if raw_path:
                entries[Path(raw_path).resolve()] = current
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return entries, None


def _registered_worktree(name: str) -> tuple[Path | None, str | None]:
    try:
        path = _worktree_path(name)
    except ValueError as exc:
        return None, str(exc)
    entries, error = _registered_worktrees()
    if error:
        return None, error
    if path not in entries:
        return None, f"worktree '{name}' is not registered with Git"
    if not path.is_dir():
        return None, f"worktree '{name}' is missing at {path}"
    expected_branch = f"refs/heads/{_worktree_branch(name)}"
    if entries[path].get("branch") != expected_branch:
        return None, (f"worktree '{name}' is not registered on expected "
                      f"branch '{_worktree_branch(name)}'")
    return path, None


def task_worktree_cwd(task: Task) -> tuple[Path, str | None]:
    """Resolve a task cwd, failing closed for broken worktree bindings."""
    if not task.worktree:
        return WORKDIR, None
    path, error = _registered_worktree(task.worktree)
    return (path or WORKDIR), error


def assignment_cwd(owner: str) -> Path:
    with task_lock:
        assignment = teammate_assignments.get(owner)
        task = _owner_in_progress(owner)
        if task and (not assignment or assignment.get("task_id") != task.id):
            cwd, error = task_worktree_cwd(task)
            if error:
                raise ValueError(error)
            assignment = {"task_id": task.id, "cwd": cwd}
            teammate_assignments[owner] = assignment
        elif not assignment:
            return WORKDIR
        task = load_task(str(assignment["task_id"]))
        if task.status not in {"in_progress", "completed"} or task.owner != owner:
            raise ValueError(f"Assignment for {owner} is no longer active")
        cwd, error = task_worktree_cwd(task)
        if error:
            raise ValueError(error)
        if cwd.resolve() != Path(assignment["cwd"]).resolve():
            raise ValueError(f"Assignment cwd changed for task {task.id}")
        return cwd


def release_completed_assignment(owner: str) -> bool:
    """Release a completed cwd lease only at a model turn boundary."""
    with task_lock:
        assignment = teammate_assignments.get(owner)
        if not assignment:
            return False
        task = load_task(str(assignment["task_id"]))
        if task.status != "completed" or task.owner != owner:
            return False
        teammate_assignments.pop(owner, None)
        advance_assignment_version(owner)
        if owner in globals().get("plan_gates", {}):
            globals()["plan_gates"][owner] = "not_required"
        return True


def release_teammate_assignment(owner: str):
    """Return abandoned teammate work to the task board on thread exit."""
    with task_lock:
        try:
            task = _owner_in_progress(owner)
            if task:
                task.status = "pending"
                task.owner = None
                save_task(task)
        finally:
            teammate_assignments.pop(owner, None)
            advance_assignment_version(owner)
            if owner in globals().get("plan_gates", {}):
                globals()["plan_gates"][owner] = "not_required"


def create_worktree(name: str, task_id: str) -> str:
    """Create and bind a dedicated worktree after all inputs validate."""
    error = validate_worktree_name(name)
    if error:
        return f"Error: {error}"
    try:
        path = _worktree_path(name)
        task_path = _task_path(task_id)
    except ValueError as exc:
        return f"Error: {exc}"
    branch = _worktree_branch(name)

    with task_lock:
        if not task_path.exists():
            return f"Error: Task {task_id} not found"
        task = load_task(task_id)
        if task.status != "pending" or task.owner is not None:
            return f"Error: Task {task_id} must be pending and unowned"
        if task.worktree:
            return f"Error: Task {task_id} already uses worktree '{task.worktree}'"
        if any(t.worktree == name for t in list_tasks() if t.id != task_id):
            return f"Error: Worktree '{name}' is already bound to another task"
        if path.exists():
            return f"Error: Worktree path already exists: {path}"

        ok, root = run_git(["rev-parse", "--show-toplevel"])
        if not ok or Path(root).resolve() != WORKDIR.resolve():
            return "Error: Working directory must be the root of a Git repository"
        ok, branch_check = run_git(["check-ref-format", "--branch", branch])
        if not ok:
            return f"Error: Invalid worktree branch '{branch}': {branch_check}"
        exists, _ = run_git(["show-ref", "--verify", "--quiet",
                             f"refs/heads/{branch}"])
        if exists:
            return f"Error: Branch '{branch}' already exists"
        entries, registry_error = _registered_worktrees()
        if registry_error:
            return f"Error: {registry_error}"
        if path in entries:
            return f"Error: Worktree path is already registered: {path}"

        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
        ok, result = run_git(["worktree", "add", "-b", branch,
                              str(path), "HEAD"])
        if not ok:
            entries, registry_error = _registered_worktrees()
            branch_exists, _ = run_git(
                ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
            )
            artifacts = []
            if path.exists():
                artifacts.append(f"checkout path '{path}'")
            if registry_error is None and path in entries:
                artifacts.append("registered Git worktree")
            if branch_exists:
                artifacts.append(f"branch '{branch}'")
            if artifacts:
                return (
                    "Partial operation: git worktree add reported an error "
                    f"after leaving {', '.join(artifacts)}. Task {task_id} "
                    "remains unbound and no Git data was deleted. Run "
                    f"`git worktree list`, inspect '{path}' and '{branch}', "
                    "then keep or remove those artifacts manually after "
                    f"preserving any work. Git error: {result}"
                )
            return f"Git error: {result}"

        try:
            task.worktree = name
            save_task(task)
        except Exception as exc:
            return (f"Partial success: Worktree '{name}' was created at "
                    f"{path} on branch '{branch}', but task binding failed: "
                    f"{exc}. Git data was retained for manual recovery.")

    print(f"  \033[33m[worktree] created: {name} at {path}\033[0m")
    return f"Worktree '{name}' created at {path} for task {task_id}"


def remove_worktree(name: str, discard_changes: bool = False) -> str:
    """Remove a registered checkout while always retaining its branch."""
    error = validate_worktree_name(name)
    if error:
        return f"Error: {error}"
    with task_lock:
        path, error = _registered_worktree(name)
        if error:
            return f"Error: {error}"
        bound = [task for task in list_tasks() if task.worktree == name]
        if not bound:
            return f"Error: Worktree '{name}' is not bound to a task"
        active = [task for task in bound if task.status != "completed"]
        if active:
            return (f"Error: Worktree '{name}' is bound to active task "
                    f"{active[0].id}; complete it before removal")
        leased = [owner for owner, assignment in teammate_assignments.items()
                  if Path(assignment["cwd"]).resolve() == path.resolve()]
        if leased:
            return (f"Error: Worktree '{name}' is still in use by "
                    f"{', '.join(sorted(leased))}; wait for the turn to end")
        with globals().get("background_lock", threading.Lock()):
            running = [task for task in globals().get("background_tasks", {}).values()
                       if task.get("status") == "running"
                       and task.get("cwd")
                       and Path(task["cwd"]).resolve() == path.resolve()]
        if running:
            return (f"Error: Worktree '{name}' has a running background command; "
                    "wait for it to finish")

        ok, status = run_git(
            ["status", "--porcelain", "--ignored"], cwd=path
        )
        if not ok:
            return f"Error: Cannot verify worktree '{name}' status: {status}"
        if status != "(no output)" and not discard_changes:
            changed = len([line for line in status.splitlines() if line.strip()])
            return (f"Error: Worktree '{name}' has {changed} uncommitted "
                    "change(s); preserve or discard them manually")

        args = ["worktree", "remove"]
        if discard_changes:
            args.append("--force")
        args.append(str(path))
        ok, result = run_git(args)
        if not ok:
            return f"Git error: {result}"

        try:
            for task in bound:
                task.worktree = None
                save_task(task)
        except Exception as exc:
            return (f"Partial success: Worktree '{name}' was removed and "
                    f"branch '{_worktree_branch(name)}' retained, but task "
                    f"unbinding failed: {exc}. Manual recovery is required.")

    print(f"  \033[33m[worktree] removed: {name}; branch retained\033[0m")
    return f"Worktree '{name}' removed; branch '{_worktree_branch(name)}' retained"
