import os
import time

from anthropic import Anthropic

client = Anthropic()
MODEL = os.environ["MODEL_ID"]
WORKDIR = os.path.realpath(os.path.expanduser("~/Downloads"))
PROTECTED = {"/", os.path.realpath(os.path.expanduser("~")), "/etc", "/usr", "/System"}

TOOLS = [
    {"name": "find_old_files", "description": "List files under the downloads folder untouched for N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]}},
    {"name": "remove_file", "description": "Remove one file (the user is asked first).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def find_old_files(days: int) -> str:
    cutoff = time.time() - days * 86400
    found = []
    for name in os.listdir(WORKDIR):
        full = os.path.join(WORKDIR, name)
        if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
            found.append(full)
    return "\n".join(found) or "nothing"


def ask_before_rm(path: str) -> str:
    real = os.path.realpath(path)
    if real in PROTECTED or not real.startswith(WORKDIR + os.sep):
        return "拒绝：只能清理下载目录里的文件"
    answer = input(f"确认删除 {real} ？输入 yes 继续：")
    if answer.strip() != "yes":
        return "用户取消了"
    os.remove(real)
    return "已删除"


HANDLERS = {"find_old_files": find_old_files, "remove_file": ask_before_rm}


def agent_loop(messages):
    while True:
        response = client.messages.create(model=MODEL, messages=messages, tools=TOOLS, max_tokens=4000)
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            return
        results = [{"type": "tool_result", "tool_use_id": b.id, "content": HANDLERS[b.name](**b.input)} for b in calls]
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    agent_loop([{"role": "user", "content": input(">> ")}])
