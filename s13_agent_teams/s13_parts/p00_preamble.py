# s13_agent_teams / p00_preamble.py —— 导入、配置与共享常量
# 本文件是 code.py 的一个分节：code.py 按文件名顺序把各分节执行进同一个命名空间，
# 因此这里可以直接使用其他分节定义的名字。请从仓库根目录运行 code.py，不要单独 import 本文件。
# ruff: noqa: F821

import fcntl
import json
import os
import random
import re
import secrets
import select
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from pathlib import Path

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
except ImportError:
    pass

from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make the root-level common/ package importable
from common.bootstrap import make_client, resolve_model, run_repl, print_last_text, require_credentials, guard  # noqa: E402

WORKDIR = Path.cwd()
client = make_client()
MODEL = resolve_model()
