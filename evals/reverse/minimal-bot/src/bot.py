import os
import subprocess
from anthropic import Anthropic

client = Anthropic()
MODEL = os.environ["MODEL_ID"]
TOOLS = [{"name": "bash", "description": "Run a shell command.",
          "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]


def run_bash(command: str) -> str:
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return r.stdout + r.stderr


def agent_loop(messages):
    while True:
        response = client.messages.create(model=MODEL, messages=messages, tools=TOOLS, max_tokens=4000)
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            return
        results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_bash(b.input["command"])} for b in calls]
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        q = input(">> ")
        history.append({"role": "user", "content": q})
        agent_loop(history)
