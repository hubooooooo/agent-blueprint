#!/usr/bin/env python3
"""
s15: 集成 Harness —— 将各组件机制整合到一个运行时中。

运行：  python s15_integrated_harness/code.py
依赖：  pip install anthropic python-dotenv pyyaml + .env 配置 ANTHROPIC_API_KEY

    定时任务 ----+                    +---- 团队事件
                v                    v
    +---------------------------------------------------+
    | Agent loop                                        |
    | prompt -> model -> tool calls -> results -> prompt |
    +-------------------------+-------------------------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
      内置工具            持久团队            MCP 工具

分节地图（按文件顺序；每节都来自前面某一章，这里只是把它们接到同一个循环上）
    grep -n '^# -- ' s15_integrated_harness/code.py 可直接列出全部小节及行号

    小节                          来源章节   作用
    ----------------------------  --------  ------------------------------------------
    Console / memory runtime      s09       终端输出代理、按需加载记忆运行时
    Task System                   s10       任务记录、依赖、认领与完成（文件锁）
    Task-bound Worktrees          s13       任务绑定的 git worktree 创建/释放
    Skill Loading                 s07       扫描 skills/ 目录，按需注入技能正文
    Prompt Assembly               s07/s09   把技能目录、记忆、上下文拼成系统提示词
    Basic Tools                   s02/s03   bash/read/write/edit/glob 与 safe_path 边界
    MessageBus and Team Protocols s13       队友信箱、消息投递、lead 收件箱
    Protocol State                s13       计划/关停请求的状态表与请求/响应匹配
    Team Task Assignment          s13       空闲队友自动认领未分配任务
    Teammate Thread               s13       队友线程：独立消息历史 + 工具子集
    Lead Team Tools               s13       lead 侧的 request_plan / review_plan / shutdown
    Hooks and Permission Checks   s03/s04   权限检查与 PreToolUse / PostToolUse / Stop 钩子
    Subagent Tool                 s06       一次性子 agent：干净上下文，只回最终文本
    Context Compaction            s08       micro / snip / 摘要三层压缩与大输出落盘
    Error Recovery                s01       指数退避重试、prompt-too-long 识别
    Background Tasks              s11       后台 bash 与结果回收通知
    Cron Scheduler                s12       cron 表达式校验、持久化、到期入队
    MCP System                    s14       MCP 客户端、mock 服务器、工具池装配
    Lead Worktree Tools           s13       lead 侧创建任务绑定 worktree 的工具函数
    Basic Tool Handlers           s10/s13   面向模型的任务、团队、MCP 连接等工具函数
    Tool Definitions              s02       全部工具的 JSON schema
    Context                       s09       每轮更新上下文并回写记忆
    Agent Loop                    s01       主循环、上下文准备、后台通知注入、异步事件循环

代码按小节放在 s15_parts/ 下，code.py 按文件名顺序把它们执行进同一个命名空间，
所以行为与过去的单文件完全一致（测试和 s16 对模块全局名的注入照常生效）：

    p00_preamble.py                          preamble
    p01_task_system.py                       Task System
    p02_task_bound_worktrees.py              Task-bound Worktrees
    p03_skill_loading.py                     Skill Loading
    p04_prompt_assembly.py                   Prompt Assembly
    p05_basic_tools.py                       Basic Tools
    p06_messagebus_and_team_protocols.py     MessageBus and Team Protocols
    p07_protocol_state.py                    Protocol State
    p08_team_task_assignment.py              Team Task Assignment
    p09_teammate_thread.py                   Teammate Thread
    p10_lead_team_tools.py                   Lead Team Tools
    p11_hooks_and_permission_checks.py       Hooks and Permission Checks
    p12_subagent_tool.py                     Subagent Tool
    p13_context_compaction.py                Context Compaction
    p14_error_recovery.py                    Error Recovery
    p15_background_tasks.py                  Background Tasks
    p16_cron_scheduler.py                    Cron Scheduler
    p17_mcp_system.py                        MCP System
    p18_lead_worktree_tools.py               Lead Worktree Tools
    p19_basic_tool_handlers.py               Basic Tool Handlers
    p20_tool_definitions.py                  Tool Definitions
    p21_context.py                           Context
    p22_agent_loop.py                        Agent Loop
    p23_main.py                              交互入口
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PARTS_DIR = _HERE / "s15_parts"


def _load_parts(namespace: dict) -> None:
    """按文件名顺序把 s15_parts/*.py 执行进本模块的命名空间。

    为什么不是 import：各小节之间互相引用模块级函数与状态，测试和后续章节也直接改写
    本模块的全局名来注入假实现；共享同一个命名空间才能保持这些行为。单独阅读某个分节时，
    看文件头的说明即可知道它依赖哪些前置分节。
    """
    for part in sorted(PARTS_DIR.glob("p[0-9][0-9]_*.py")):
        exec(compile(part.read_text(encoding="utf-8"), str(part), "exec"), namespace)


_load_parts(globals())

if __name__ == "__main__":
    run_cli()  # noqa: F821 - 定义在 s15_parts/p23_main.py
