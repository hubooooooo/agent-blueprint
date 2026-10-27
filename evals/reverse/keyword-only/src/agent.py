import os
import smtplib
from email.message import EmailMessage

from anthropic import Anthropic

from permissions import check_permission
from memory import remember

client = Anthropic()
MODEL = os.environ["MODEL_ID"]
TOOLS = [
    {"name": "read_sheet", "description": "Read this week's sheet.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "send_mail", "description": "Send the report to the whole team.",
     "input_schema": {"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}},
]


def read_sheet(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def send_mail(body: str) -> str:
    # permission: 发邮件前应该先确认（deny list / allow list 以后再说）
    check_permission("send_mail")
    msg = EmailMessage()
    msg["To"] = os.environ["TEAM_LIST"]
    msg["Subject"] = "本周周报"
    msg.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"]) as s:
        s.send_message(msg)
    remember("last_report", body)
    return "sent"


HANDLERS = {"read_sheet": read_sheet, "send_mail": send_mail}


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
    agent_loop([{"role": "user", "content": "写本周周报并发给全组，数据在 data/week.csv"}])
