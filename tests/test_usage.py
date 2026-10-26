"""产品累计用量（blueprint/usage.py）：推导任务和对话都要记，中途失败或断开也不漏记。"""
import time

from blueprint.llm import Budget
from blueprint.mock import MockRunner
from blueprint.usage import USAGE_FILE, read_usage, record_usage
from blueprint.web.server import App, metered

IDEA = "家长拍一张玩具合影，AI 生成亲子剧情脚本。照片涉及隐私，默认不保存。"


def _budget(calls, inp=100, out=50):
    b = Budget()
    for _ in range(calls):
        b.record("x", inp, out)
    return b


def test_records_accumulate_by_kind(tmp_path):
    assert read_usage(tmp_path)["total"] == {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    record_usage(tmp_path, "plan", _budget(3))
    record_usage(tmp_path, "plan", _budget(1))
    record_usage(tmp_path, "chat", _budget(2, 10, 5))
    u = read_usage(tmp_path)
    assert u["plan"] == {"calls": 4, "input_tokens": 400, "output_tokens": 200}
    assert u["chat"] == {"calls": 2, "input_tokens": 20, "output_tokens": 10}
    assert u["total"]["calls"] == 6


def test_mock_runner_and_empty_budget_write_nothing(tmp_path):
    record_usage(tmp_path, "plan", None)
    record_usage(tmp_path, "chat", Budget())
    assert not (tmp_path / USAGE_FILE).exists()


def test_corrupt_file_reads_as_zero(tmp_path):
    (tmp_path / USAGE_FILE).write_text("{坏了", encoding="utf-8")
    assert read_usage(tmp_path)["total"]["calls"] == 0


class FakeChat:
    def __init__(self):
        self.runner = type("R", (), {"budget": Budget()})()

    def events(self):
        for i in range(3):
            self.runner.budget.record("chat", 7, 3)
            yield {"type": "text", "delta": str(i)}


def test_metered_chat_records_after_stream_and_on_disconnect(tmp_path):
    model = FakeChat()
    assert len(list(metered(tmp_path, model, model.events()))) == 3
    assert read_usage(tmp_path)["chat"]["calls"] == 3

    model = FakeChat()
    gen = metered(tmp_path, model, model.events())
    next(gen)
    gen.close()                                   # 用户中途点了停止
    assert read_usage(tmp_path)["chat"] == {"calls": 4, "input_tokens": 28, "output_tokens": 12}


class CountingRunner(MockRunner):
    """离线 runner 加上计费：每次调用记 10/5 tokens；fail_after 次之后报错。"""

    def __init__(self, fail_after=None):
        super().__init__()
        self.budget = Budget()
        self.fail_after = fail_after

    def complete(self, stage, system, prompt, schema):
        if self.fail_after is not None and self.budget.calls >= self.fail_after:
            raise RuntimeError("网络断了")
        self.budget.record(stage, 10, 5)
        return super().complete(stage, system, prompt, schema)


def _wait(job):
    deadline = time.time() + 10
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    return job


def test_plan_job_records_usage_even_when_it_fails(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "MODEL_ID", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    app = App(tmp_path / "out", env_path=tmp_path / ".env", mock=True)
    runners = [CountingRunner(fail_after=2), CountingRunner()]
    monkeypatch.setattr(app, "make_runner", lambda: runners.pop(0))

    res = app.create_product({"name": "玩具剧场", "idea": IDEA})
    assert _wait(app.jobs.get(res["job"]["id"])).status == "failed"
    assert app.product(res["slug"])["usage"]["plan"]["calls"] == 2       # 失败前的两次照样计入

    assert _wait(app.start_plan(res["slug"])).status == "done"
    usage = app.product(res["slug"])["usage"]
    assert usage["plan"]["calls"] > 2 and usage["total"] == usage["plan"]
