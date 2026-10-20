# s15_integrated_harness / p23_main.py —— 交互入口
# 本文件是 code.py 的一个分节，在同一个命名空间里执行；code.py 的 __main__ 只调用这里的 run_cli()。
# ruff: noqa: F821

def run_cli():
    """交互入口：原来写在 if __name__ == "__main__": 下面的内容。"""
    global CLI_ACTIVE
    require_credentials()
    CLI_ACTIVE = True
    start_runtime_services()
    print("s15: integrated harness")
    print("Enter a question, press Enter to send. Type q to quit.\n")
    history = []
    context = update_context({}, [])
    session_state = {"active_user_request": "(no active user request)"}
    threading.Thread(target=async_event_loop,
                     args=(history, context, session_state), daemon=True).start()
    while True:
        try:
            query = CONSOLE.ask(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with agent_lock:
            trigger_hooks("UserPromptSubmit", query)
            turn_start = len(history)
            session_state["active_user_request"] = query
            history.append({"role": "user", "content": query})
            guard(lambda: agent_loop(history, context, query))
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)
        print()
