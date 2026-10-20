# s13_agent_teams / p12_agent_loop.py —— 小节「Agent Loop」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- Agent Loop --

def agent_loop(messages: list):
    while True:
        try:
            response = client.messages.create(
                model=MODEL,
                system=SYSTEM,
                messages=messages,
                tools=TOOLS,
                max_tokens=8000,
            )
        except Exception as exc:
            messages.append({
                "role": "assistant",
                "content": [{
                    "type": "text",
                    "text": f"[Error] {type(exc).__name__}: {exc}",
                }],
            })
            release_completed_assignment("agent")
            trigger_hooks("Stop", messages)
            return

        messages.append({"role": "assistant", "content": response.content})
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        if not tool_calls:
            release_completed_assignment("agent")
            trigger_hooks("Stop", messages)
            return

        results = []
        for block in tool_calls:
            print(f"> {block.name}")
            output = execute_tool(block)
            print(output[:300])
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})


def print_last_assistant_message(history: list):
    if not history:
        return
    for block in history[-1].get("content", []):
        if getattr(block, "type", None) == "text":
            print(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            print(block.get("text", ""))


def wait_for_cli_event() -> tuple[str, str | None]:
    prompt_visible = False
    while True:
        if BUS.peek("lead"):
            if prompt_visible:
                print()
            return "wake", None
        if not prompt_visible:
            print("s13 >> ", end="", flush=True)
            prompt_visible = True
        readable, _, _ = select.select([sys.stdin], [], [], 0.25)
        if readable:
            line = sys.stdin.readline()
            if line == "":
                return "quit", None
            return "user", line.rstrip("\n")
