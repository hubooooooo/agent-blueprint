"""后台任务：推导要跑几分钟，放到线程里执行，页面轮询进度。"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from blueprint.llm import BudgetExceeded, StageOutputInvalid

RESUME_HINT = "点「继续推导」从断点接着跑，已完成的阶段不会重复调用模型。"


def friendly_error(exc: BaseException) -> str:
    """把底层异常转述成小白看得懂的话；anthropic 的异常按类名判断，不在这里硬依赖 SDK。"""
    name = type(exc).__name__
    if isinstance(exc, BudgetExceeded):
        return f"达到本次运行的费用上限（{exc}），已自动停下。{RESUME_HINT}"
    if isinstance(exc, StageOutputInvalid):
        return f"模型这一步的输出格式不对：{exc}。{RESUME_HINT}"
    if name == "AuthenticationError":
        return "API Key 无效或已过期，请到「模型设置」重新填写。"
    if name == "PermissionDeniedError":
        return "模型服务拒绝了请求，常见原因是账户余额不足或没有该模型的权限，请到服务商后台检查。"
    if name in ("APIConnectionError", "APITimeoutError"):
        return f"连不上模型服务（网络或服务商地址有问题）。检查网络后{RESUME_HINT}"
    if name == "RateLimitError":
        return f"请求太频繁或额度用完了，稍等一会儿再试。{RESUME_HINT}"
    if name == "NotFoundError":
        return "模型名不存在，请到「模型设置」检查模型名。"
    if name in ("InternalServerError", "ServiceUnavailableError", "OverloadedError") or (
            name == "APIStatusError" and getattr(exc, "status_code", 0) >= 500):
        return f"模型服务那边暂时出错了（{getattr(exc, 'status_code', '') or name}），不是你的问题。稍等一会儿，{RESUME_HINT}"
    if isinstance(exc, ValueError):
        return str(exc)
    return f"出错了：{name}: {exc}"


@dataclass
class Job:
    id: str
    kind: str
    slug: str
    status: str = "running"          # running | done | failed
    logs: list[str] = field(default_factory=list)
    error: str = ""
    result: dict | None = None        # 任务函数的返回值，比如加新需求后的选型变化
    started: float = field(default_factory=time.time)
    finished: float | None = None

    def log(self, message: str) -> None:
        self.logs.append(message.rstrip())

    def to_dict(self, since: int = 0) -> dict:
        return {"id": self.id, "kind": self.kind, "slug": self.slug, "status": self.status,
                "logs": self.logs[since:], "log_count": len(self.logs), "error": self.error, "result": self.result,
                "started": self.started, "finished": self.finished}


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, str] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def start(self, kind: str, slug: str, fn: Callable[[Callable[[str], None]], dict | None]) -> Job:
        with self._lock:
            current = self.latest_for(slug)
            if current and current.status == "running":
                raise ValueError("这个项目正在检查中，等它跑完再操作。" if kind == "audit"
                                 else "这个产品正在推导中，等它跑完再操作。")
            job = Job(id=str(next(self._ids)), kind=kind, slug=slug)
            self._jobs[job.id] = job
            self._latest[slug] = job.id
        threading.Thread(target=self._run, args=(job, fn), daemon=True).start()
        return job

    def _run(self, job: Job, fn: Callable[[Callable[[str], None]], dict | None]) -> None:
        try:
            job.result = fn(job.log)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 —— 任何失败都要落到页面上，不能让线程悄悄死掉
            job.error = friendly_error(exc)
            job.log(f"✗ {job.error}")
            job.status = "failed"
        finally:
            job.finished = time.time()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest_for(self, slug: str) -> Job | None:
        job_id = self._latest.get(slug)
        return self._jobs.get(job_id) if job_id else None
