# s15_integrated_harness / p18_lead_worktree_tools.py —— 小节「Lead Worktree Tools」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Lead Worktree Tools --

def run_create_worktree(name: str, task_id: str) -> str:
    return create_worktree(name, task_id)
