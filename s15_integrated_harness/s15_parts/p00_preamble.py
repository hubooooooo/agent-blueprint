# s15_integrated_harness / p00_preamble.py —— 导入、配置与共享常量
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

import ast
import atexit
import fcntl
import importlib.util
import json
import os
import random
import re
import secrets
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
import yaml

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

from anthropic import Anthropic
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make the root-level common/ package importable
from common.bootstrap import make_client, resolve_model, run_repl, print_last_text, require_credentials, guard  # noqa: E402

WORKDIR = Path.cwd()
client = make_client()
MODEL = resolve_model()
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36ms15 >> \033[0m"
CLI_ACTIVE = False


def load_memory_runtime():
    """Load s09 once and share this host's client, model, and workspace."""
    path = Path(__file__).resolve().parents[1] / "s09_memory" / "code.py"
    spec = importlib.util.spec_from_file_location(
        f"integrated_memory_{id(client)}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load memory runtime from {path}")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    runtime.WORKDIR = WORKDIR
    runtime.MEMORY_DIR = WORKDIR / ".memory"
    runtime.MEMORY_INDEX = runtime.MEMORY_DIR / "MEMORY.md"
    runtime.client = client
    runtime.MODEL = MODEL
    return runtime


MEMORY_RUNTIME = load_memory_runtime()


class ConsoleBroker:
    """Serialize normal prompts and worker permission questions on one stdin."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reader = None

    def ask(self, prompt: str) -> str:
        with self._lock:
            return (self.reader or input)(prompt)


CONSOLE = ConsoleBroker()


def terminal_print(text: str):
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)
