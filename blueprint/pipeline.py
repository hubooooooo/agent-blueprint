"""阶段执行与断点续跑：每个阶段的输出落盘到 out/<name>/stages/<stage>.json。"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Callable

from blueprint.knowledge import load_prompt
from blueprint.llm import Runner, StageOutputInvalid
from blueprint.schema import validate

SYSTEM = load_prompt("common_system")


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    """同目录替换，避免中断时留下半份 JSON 或报告。"""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".blueprint-", delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class StageRunner:
    def __init__(self, runner: Runner, out_dir: Path, resume: bool = False,
                 log: Callable[[str], None] = print, context: dict | None = None):
        self.runner = runner
        self.out_dir = Path(out_dir)
        self.stages_dir = self.out_dir / "stages"
        self.resume = resume
        self.log = log
        self.chain = _digest(context or {})
        self.stages_dir.mkdir(parents=True, exist_ok=True)

    def run(self, stage: str, prompt: str, schema: dict, label: str = "") -> dict:
        path = self.stages_dir / f"{stage}.json"
        meta_path = self.stages_dir / f"{stage}.meta.json"
        signature = _digest({"version": 1, "chain": self.chain, "stage": stage,
                             "system": SYSTEM, "prompt": prompt, "schema": schema,
                             "runner": getattr(self.runner, "name", ""),
                             "model": getattr(self.runner, "model", "")})
        if self.resume and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if (meta.get("signature") == signature and meta.get("output") == _digest(data)
                        and not validate(schema, data)):
                    self.log(f"  ↻ {label or stage}：沿用上次结果")
                    self.chain = _digest([signature, data])
                    return data
            except (OSError, ValueError, AttributeError):
                pass
            self.log(f"  ↻ {label or stage}：输入、配置或缓存已变化，重新执行")
        self.log(f"  ▶ {label or stage}")
        data = self.runner.complete(stage, SYSTEM, prompt, schema)
        errors = validate(schema, data)
        if errors:
            raise StageOutputInvalid(f"阶段 {stage} 输出不合格式：{errors}")
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
        atomic_write(meta_path, json.dumps({"signature": signature, "output": _digest(data)}))
        self.chain = _digest([signature, data])
        return data

    def save(self, name: str, content: str) -> Path:
        path = self.out_dir / name
        atomic_write(path, content)
        return path

    def save_json(self, name: str, data: dict) -> Path:
        return self.save(name, json.dumps(data, ensure_ascii=False, indent=2))
