# s15_integrated_harness / p06_messagebus_and_team_protocols.py —— 小节「MessageBus and Team Protocols」
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

# -- MessageBus and Team Protocols --

MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_ROOT = MAILBOX_DIR.resolve()
VALID_AGENT_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RESERVED_TEAMMATE_NAMES = {"lead", "agent"}


def is_valid_agent_name(name: str) -> bool:
    return bool(VALID_AGENT_NAME.fullmatch(name))


class MessageBus:
    def __init__(self):
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)

    def _path(self, agent: str) -> Path:
        if not is_valid_agent_name(agent):
            raise ValueError(f"Invalid mailbox recipient: {agent!r}")
        path = (MAILBOX_DIR / f"{agent}.jsonl").resolve()
        if not path.is_relative_to(MAILBOX_ROOT):
            raise ValueError(f"Mailbox path escapes directory: {agent!r}")
        return path

    def _read_unlocked(self, agent: str) -> list[dict]:
        inbox = self._path(agent)
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line in inbox.read_text().splitlines()
                if line.strip()]
        inbox.unlink()
        return msgs

    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict | None = None):
        msg = {"from": from_agent, "to": to_agent,
               "content": content, "type": msg_type,
               "ts": time.time(), "metadata": metadata or {}}
        with self._changed:
            MAILBOX_DIR.mkdir(parents=True, exist_ok=True)
            with self._path(to_agent).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(msg, ensure_ascii=True) + "\n")
            self._changed.notify_all()
        print(f"  \033[33m[bus] {from_agent} -> {to_agent}: "
              f"({msg_type}) {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list[dict]:
        with self._lock:
            return self._read_unlocked(agent)

    def peek(self, agent: str) -> bool:
        with self._lock:
            inbox = self._path(agent)
            return inbox.exists() and inbox.stat().st_size > 0

    def wait_for_messages(self, agent: str,
                          timeout: float | None = None) -> list[dict]:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._changed:
            while not self.peek(agent):
                remaining = (None if deadline is None
                             else deadline - time.monotonic())
                if remaining is not None and remaining <= 0:
                    return []
                self._changed.wait(remaining)
            return self._read_unlocked(agent)


BUS = MessageBus()
active_teammates: dict[str, str] = {}
plan_gates: dict[str, str] = {}
plan_request_ids: dict[str, str] = {}
team_lock = threading.RLock()
