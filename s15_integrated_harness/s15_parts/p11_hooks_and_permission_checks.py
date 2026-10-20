# s15_integrated_harness / p11_hooks_and_permission_checks.py —— 小节「Hooks and Permission Checks」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Hooks and Permission Checks --

# Hooks are intentionally outside tool handlers. The loop can add permission,
# logging, and stop behavior without changing each individual tool.
HOOKS = {"UserPromptSubmit": [], "PreToolUse": [],
         "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
mcp_tool_policies: dict[str, str] = {}


def permission_hook(block):
    # The permission layer sees the raw tool_use before dispatch. It can deny,
    # ask the user, or allow execution to continue.
    if block.name == "bash":
        command = block.input.get("command", "")
        if not isinstance(command, str):
            return "Permission denied: shell command must be a string"
        for pattern in DENY_LIST:
            if pattern in command:
                return f"Permission denied: '{pattern}' is on the deny list"
        if threading.current_thread() is not threading.main_thread():
            return ("Permission denied: interactive shell approval is unavailable "
                    "during an asynchronous turn")
        terminal_print("\n\033[33m[permission] shell command\033[0m")
        terminal_print(f"  {command}")
        choice = CONSOLE.ask("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not isinstance(path, str):
            return "Permission denied: path must be a string"
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            return "Permission denied: path is outside the workspace"
    if (block.name.startswith("mcp__")
            and mcp_tool_policies.get(block.name, "confirm") != "allow"):
        if threading.current_thread() is not threading.main_thread():
            return ("Permission denied: interactive MCP approval is unavailable "
                    "during an asynchronous turn")
        terminal_print(f"\n\033[33m[permission] MCP tool: {block.name}\033[0m")
        choice = CONSOLE.ask("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    return None


def log_hook(block):
    print(f"\033[90m[HOOK] {block.name}\033[0m")
    return None


def large_output_hook(block, output):
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] large output from {block.name}: "
              f"{len(str(output))} chars\033[0m")
    return None


def user_prompt_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: {WORKDIR}\033[0m")
    return None


def stop_hook(messages: list):
    tool_count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content
                              if isinstance(item, dict)
                              and item.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: {tool_count} tool result(s)\033[0m")
    return None


register_hook("UserPromptSubmit", user_prompt_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)
