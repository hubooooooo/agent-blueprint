"""s15 的显式扩展点：注册的扩展在 assemble_tool_pool 末尾执行，s16 通过它加装 Workflow 而不替换函数。"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    previous = os.environ.get("MODEL_ID")
    os.environ["MODEL_ID"] = "test-model"
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("MODEL_ID", None)
        else:
            os.environ["MODEL_ID"] = previous


def test_register_tool_extension_runs_at_the_end_and_is_idempotent():
    host = _load("s15_ext_test", ROOT / "s15_integrated_harness" / "code.py")
    seen = []

    def extend(tools, handlers):
        seen.append(len(tools))
        tools.append({"name": "Extra", "description": "x", "input_schema": {"type": "object", "properties": {}}})
        handlers["Extra"] = lambda: "extra"
        return tools, handlers

    host.register_tool_extension(extend)
    host.register_tool_extension(extend)
    assert host.TOOL_POOL_EXTENSIONS.count(extend) == 1
    tools, handlers = host.assemble_tool_pool()
    assert tools[-1]["name"] == "Extra" and handlers["Extra"]() == "extra"
    assert seen == [len(host.BUILTIN_TOOLS)]
    assert host.assemble_tool_pool.__name__ == "assemble_tool_pool"   # 没有被替换


def test_s16_installs_workflow_through_the_registry_not_by_monkeypatching():
    workflow = _load("s16_ext_test", ROOT / "s16_workflow_runtime" / "code.py")
    host = workflow.load_integrated_host()
    workflow.install_workflow_tool(host)
    assert workflow.add_workflow_tool in host.TOOL_POOL_EXTENSIONS
    assert host.assemble_tool_pool.__name__ == "assemble_tool_pool"
    tools, handlers = host.assemble_tool_pool()
    assert [t["name"] for t in tools].count("Workflow") == 1
    assert handlers["Workflow"] is workflow.run_workflow_sync
    workflow.install_workflow_tool(host)                               # 再装一次不重复
    assert host.TOOL_POOL_EXTENSIONS.count(workflow.add_workflow_tool) == 1
