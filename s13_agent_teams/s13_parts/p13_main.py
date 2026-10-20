# s13_agent_teams / p13_main.py —— 交互入口
# 本文件是 code.py 的一个分节，在同一个命名空间里执行；code.py 的 __main__ 只调用这里的 run_cli()。
# ruff: noqa: F821

def run_cli():
    """交互入口：原来写在 if __name__ == "__main__": 下面的内容。"""
    print("s13: agent teams")
    print("Enter a question, press Enter to send. Type q to quit.\n")
    require_credentials()
    history = []
    had_teammates = False

    while True:
        kind, payload = wait_for_cli_event()
        if kind == "quit":
            break
        if kind == "user":
            if payload is None or payload.strip().lower() in {"q", "exit", ""}:
                break
            trigger_hooks("UserPromptSubmit", payload)
            history.append({"role": "user", "content": payload})
        else:
            inbox = consume_lead_inbox()
            if not inbox:
                continue
            history.append({
                "role": "user",
                "content": format_team_events(inbox),
            })
            print(f"[wake: {len(inbox)} team event(s) -> new turn]")

        if not guard(lambda: agent_loop(history)):
            continue
        print_last_assistant_message(history)

        if active_teammates:
            had_teammates = True
        elif had_teammates and not BUS.peek("lead"):
            print("[all teammates shut down]")
            had_teammates = False
        print()
