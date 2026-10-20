#!/usr/bin/env python3
"""
s13: Agent Teams - persistent teammates with shared tasks and mailboxes.

Run:  python s13_agent_teams/code.py
Need: pip install anthropic python-dotenv + .env with ANTHROPIC_API_KEY

    +------+  spawn(task_id)  +----------+  result  +------+
    | Lead | ---------------> |   WORK   | -------> | IDLE |
    +--+---+                  +----+-----+          +--+---+
       ^                           |                   |
       | team events               | tools             | wait
       |                           v                   v
    +--+-----------+          +----------+        +----------+
    | MessageBus   |          | Task cwd | <----- | Mailbox  |
    +--------------+          +----------+  claim +----------+

    .tasks/       shared task records and dependencies
    .mailboxes/   messages, results, and protocol responses
    .worktrees/   optional task-bound working directories

Section map (file order; grep -n '^# -- ' s13_agent_teams/code.py lists them with line numbers)

    Section                        From   Purpose
    -----------------------------  -----  ---------------------------------------------
    Task System                    s10    task records, dependencies, claim/complete (file lock)
    Task-bound Worktrees           new    git worktree per task, create/release/remove
    System Prompt                  s01    lead prompt describing team protocols
    Base Tools                     s02    bash/read/write/edit/glob confined by safe_path
    Task Tools                     s10    model-facing task handlers
    MessageBus and Team Protocols  new    mailboxes, protocol state, request/response matching
    Idle Task Discovery            new    idle teammates claim the next unblocked task
    Teammate Runtime               new    per-teammate thread: own history, tool subset, lifecycle
    Lead Team Tools                new    spawn / list / send / request_plan / review_plan / shutdown
    Tool Definitions               s02    JSON schemas for every tool above
    Hooks and Permission Checks    s03/04 permission gate and PreToolUse/PostToolUse/Stop hooks
    Agent Loop                     s01    lead loop, CLI event wait, printing

代码按小节放在 s13_parts/ 下，code.py 按文件名顺序把它们执行进同一个命名空间，
所以行为与过去的单文件完全一致（测试和 s16 对模块全局名的注入照常生效）：

    p00_preamble.py                          preamble
    p01_task_system.py                       Task System
    p02_task_bound_worktrees.py              Task-bound Worktrees
    p03_system_prompt.py                     System Prompt
    p04_base_tools.py                        Base Tools
    p05_task_tools.py                        Task Tools
    p06_messagebus_and_team_protocols.py     MessageBus and Team Protocols
    p07_idle_task_discovery.py               Idle Task Discovery
    p08_teammate_runtime.py                  Teammate Runtime
    p09_lead_team_tools.py                   Lead Team Tools
    p10_tool_definitions.py                  Tool Definitions
    p11_hooks_and_permission_checks.py       Hooks and Permission Checks
    p12_agent_loop.py                        Agent Loop
    p13_main.py                              交互入口
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PARTS_DIR = _HERE / "s13_parts"


def _load_parts(namespace: dict) -> None:
    """按文件名顺序把 s13_parts/*.py 执行进本模块的命名空间。

    为什么不是 import：各小节之间互相引用模块级函数与状态，测试和后续章节也直接改写
    本模块的全局名来注入假实现；共享同一个命名空间才能保持这些行为。单独阅读某个分节时，
    看文件头的说明即可知道它依赖哪些前置分节。
    """
    for part in sorted(PARTS_DIR.glob("p[0-9][0-9]_*.py")):
        exec(compile(part.read_text(encoding="utf-8"), str(part), "exec"), namespace)


_load_parts(globals())

if __name__ == "__main__":
    run_cli()  # noqa: F821 - 定义在 s13_parts/p13_main.py
