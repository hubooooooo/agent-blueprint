# s15_integrated_harness / p21_context.py —— 小节「Context」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Context --


def update_context(context: dict, messages: list) -> dict:
    return {
        "memory_catalog": MEMORY_RUNTIME.read_memory_index(),
        "memories": MEMORY_RUNTIME.load_memories(messages),
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


def remember_after_turn(messages: list) -> None:
    if MEMORY_RUNTIME.extract_memories(messages):
        MEMORY_RUNTIME.consolidate_memories()
