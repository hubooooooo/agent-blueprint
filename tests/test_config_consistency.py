"""默认模型、依赖清单等配置只允许有一个事实来源；此处守住它们不再漂移。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"\'')
    raise AssertionError(f"{path} 缺少 {key}")


def test_default_model_is_consistent_everywhere():
    from blueprint.llm import DEFAULT_MODEL
    from common.bootstrap import DEFAULT_MODEL as DEMO_DEFAULT

    assert DEMO_DEFAULT == DEFAULT_MODEL
    assert _env_value(ROOT / ".env.example", "MODEL_ID") == DEFAULT_MODEL
    assert _env_value(ROOT / "scaffold/.env.example", "MODEL_ID") == DEFAULT_MODEL

    agent = (ROOT / "scaffold/agent.py").read_text(encoding="utf-8")
    m = re.search(r'os\.getenv\("MODEL_ID",\s*"([^"]+)"\)', agent)
    assert m and m.group(1) == DEFAULT_MODEL, "scaffold/agent.py 的默认模型与 DEFAULT_MODEL 不一致"

    config = (ROOT / "scaffold/config.example.yaml").read_text(encoding="utf-8")
    m = re.search(r"^model:\s*(\S+)", config, re.M)
    assert m and m.group(1) == DEFAULT_MODEL

    wizard = (ROOT / "tools/wizard.py").read_text(encoding="utf-8")
    m = re.search(r'"key": "anthropic".*?"model": "([^"]+)"', wizard, re.S)
    assert m and m.group(1) == DEFAULT_MODEL, "tools/wizard.py 的 Anthropic 默认模型不一致"


def test_requirements_include_pytest_and_ci_does_not_reinstall_it():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^pytest==", reqs, re.M), "pytest 应锁定在 requirements.txt 中"
    ci = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "requirements.txt pytest" not in ci


def test_student_package_ships_common_bootstrap():
    import importlib.util
    spec = importlib.util.spec_from_file_location("package_student", ROOT / "tools/package_student.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = {p.relative_to(ROOT).as_posix() for p in mod.collect_files(ROOT)}
    assert "common/bootstrap.py" in names
    assert "common/__init__.py" in names
