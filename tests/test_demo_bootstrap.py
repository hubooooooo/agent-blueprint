"""17 个组件 demo 共用的启动层：无 Key 时友好退出，API 异常不打印堆栈。"""
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common import bootstrap  # noqa: E402

CHAPTERS = sorted(p for p in ROOT.glob("s[0-9][0-9]_*") if (p / "code.py").is_file())


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("ANTHROPIC_") and k not in {"MODEL_ID"}}
    env.update({"BLUEPRINT_SKIP_DOTENV": "1", "ANTHROPIC_API_KEY": "sk-ant-xxx",
                "MODEL_ID": "test-model", "PYTHONIOENCODING": "utf-8"})
    env.update(extra)
    return env


def test_chapter_count():
    assert len(CHAPTERS) == 17


@pytest.mark.parametrize("chapter", CHAPTERS, ids=[c.name for c in CHAPTERS])
def test_demo_exits_cleanly_without_api_key(chapter: Path, tmp_path: Path):
    """占位 Key 启动每个 demo 并输入一句话：应退出码 1、给出中文提示、没有 Traceback。"""
    result = subprocess.run(
        [sys.executable, str(chapter / "code.py")],
        input="你好\n", capture_output=True, text=True, timeout=120,
        cwd=tmp_path, env=_clean_env(),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 1, f"{chapter.name} 退出码 {result.returncode}:\n{out[-800:]}"
    assert "Traceback" not in out, f"{chapter.name} 打印了堆栈:\n{out[-800:]}"
    assert "API Key" in out, f"{chapter.name} 没有给出配置提示:\n{out[-800:]}"


def test_has_credentials_rejects_placeholders(monkeypatch):
    monkeypatch.setenv("BLUEPRINT_SKIP_DOTENV", "1")
    monkeypatch.setattr(bootstrap, "_ENV_LOADED", False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for bad in ("", "sk-ant-xxx", "your-key-here", "PLACEHOLDER"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", bad)
        assert not bootstrap.has_credentials(), bad
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-looking-key")
    assert bootstrap.has_credentials()


def _status_error(cls, status: int):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid/v1/messages"))
    return cls("boom", response=response, body=None)


def test_friendly_api_error_translates_sdk_exceptions():
    import anthropic
    assert "401" in bootstrap.friendly_api_error(_status_error(anthropic.AuthenticationError, 401))
    assert "404" in bootstrap.friendly_api_error(_status_error(anthropic.NotFoundError, 404))
    assert "429" in bootstrap.friendly_api_error(_status_error(anthropic.RateLimitError, 429))
    conn = anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    assert "连不上" in bootstrap.friendly_api_error(conn)
    assert bootstrap.friendly_api_error(ValueError("x")) is None


def test_guard_prints_hint_and_reraises_unknown(capsys):
    import anthropic
    err = _status_error(anthropic.AuthenticationError, 401)

    def boom():
        raise err

    assert bootstrap.guard(boom) is False
    assert "401" in capsys.readouterr().out
    with pytest.raises(ValueError):
        bootstrap.guard(lambda: (_ for _ in ()).throw(ValueError("x")))


def test_print_last_text_handles_dict_object_and_str(capsys):
    class Block:
        type = "text"
        text = "obj"

    bootstrap.print_last_text([{"role": "assistant", "content": [Block(), {"type": "text", "text": "dict"}]}])
    bootstrap.print_last_text([{"role": "assistant", "content": "plain"}])
    assert capsys.readouterr().out.splitlines() == ["obj", "dict", "plain"]
