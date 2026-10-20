# s13_agent_teams / p07_idle_task_discovery.py —— 小节「Idle Task Discovery」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Idle Task Discovery --

IDLE_SCAN_INTERVAL = 2.0


def scan_unclaimed_tasks() -> list[Task]:
    """Return ready tasks whose optional worktree binding is usable."""
    with task_lock:
        ready = []
        for task in list_tasks():
            if (task.status != "pending" or task.owner is not None
                    or not can_start(task.id)):
                continue
            _, error = task_worktree_cwd(task)
            if not error:
                ready.append(task)
        return ready


def claim_next_task(name: str) -> Task | None:
    """Claim the first still-available task, never a second assignment."""
    with task_lock:
        if teammate_assignments.get(name) or _owner_in_progress(name):
            return None
    for task in scan_unclaimed_tasks():
        result = claim_task(task.id, owner=name)
        if result.startswith("Claimed "):
            return load_task(task.id)
    return None
