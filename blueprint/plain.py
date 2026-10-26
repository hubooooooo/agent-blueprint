"""待确认问题的大白话版本，给网页界面用（方案.md 仍保留原问题，给开发者看）。

两类来源分开处理：
- 组件类问题（某个组件「待确认」时生成）：问题固定，这里手写好大白话版本，不花钱。
- 模型写的问题（需求拆解的 unknowns、架构设计的 open_questions）：推导完后多调一次模型，
  改写成大白话，并分出「问提出想法的人」和「交给开发者的技术备注」。结果缓存在 stages/plain.json，
  问题没变就不重复调用；改写失败或没跑过时回退到原问题，不影响方案本身。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from blueprint.knowledge import COMPONENT_BY_ID, FEATURE_BY_ID, load_prompt

# 与 knowledge.FEATURES 一一对应；tests/test_plain_questions.py 守护不漏。
FEATURE_PLAIN = {
    "destructive_ops": "这个产品会不会替用户做「做了就收不回来」的事？比如删东西、花钱、替用户发消息，或者要碰照片、身份证这类隐私信息。",
    "audit_needed": "需不需要把 AI 做过的每件事都记下来、以后能查？或者有些操作要先拦下来，审核通过再放行？",
    "multi_step": "一次任务是不是要分好几步慢慢做，中途能停下、能告诉用户做到哪了？比如先列个计划，再一步步完成。",
    "context_heavy": "会不会有一次要翻大量材料的活？比如读几百页文档，或者同时查好几个方向，需要分给几个「小助手」分头干。",
    "large_knowledge": "AI 需要掌握的专业资料多不多？比如一大套规章制度、产品手册，用到哪部分再翻哪部分。",
    "long_sessions": "用户和 AI 会不会一聊就很久，或者中间要处理大量记录，担心 AI 记不住前面说过的话？",
    "cross_session_memory": "下次再用的时候，AI 需要记得这个用户上次的情况和偏好吗？比如孩子的年龄、喜欢的风格。",
    "persistent_goals": "有没有要做好几天的大任务，关掉电脑后下次还要接着做？",
    "slow_operations": "有没有特别慢的步骤（要几分钟以上），希望用户不用干等，可以先去做别的？",
    "scheduled": "需要 AI 到点自己干活吗？比如每天早上 8 点自动整理一遍。",
    "parallel_isolated": "要不要好几个 AI 同时干不同的活、互不干扰，像一个小团队分工合作？",
    "external_ecosystem": "需要接上现成的外部工具或插件吗？比如公司已有的系统、日历、网盘。",
    "fixed_orchestration": "整个流程是不是每次都按固定顺序走，比如「上传 → 翻译 → 校对 → 保存」，中间不需要 AI 自己判断走哪条路？",
    "auto_completion": "需要 AI 自己判断「活干完没有、干得够不够好」，不够好就自己返工吗？",
}

PLAIN_STAGE = "chat_plain_questions"
PLAIN_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "plain", "audience"],
                "properties": {
                    "index": {"type": "integer"},
                    "plain": {"type": "string"},
                    "audience": {"type": "string", "enum": ["user", "dev"]},
                },
            },
        }
    },
}


def model_questions(plan: dict) -> list[str]:
    """模型写的待确认问题：需求拆解的 unknowns + 架构设计的 open_questions，与 方案.md 的清单同序。"""
    return [str(q) for q in list(plan.get("unknowns", [])) + list(plan.get("design", {}).get("open_questions", []) or [])]


def component_questions(plan: dict) -> list[dict]:
    out = []
    for c in plan.get("components", []):
        if c.get("decision") != "待确认":
            continue
        feat = FEATURE_BY_ID.get(c.get("feature", ""))
        original = f"【组件 {c['id']} {c['name']}】{feat.question if feat else c.get('feature', '')}"
        plain = FEATURE_PLAIN.get(c.get("feature", ""), original)
        out.append({"text": f"{plain}（关系到组件 {c['id']} {c['name']}）", "original": original,
                    "audience": "user", "component": c["id"]})
    return out


def load_rewrites(ws: Path) -> dict[str, dict]:
    """stages/plain.json → {原问题: {"plain", "audience"}}；没有或损坏就返回空，调用方回退到原问题。"""
    path = Path(ws) / "stages" / f"{PLAIN_STAGE}.json"
    source = Path(ws) / "stages" / f"{PLAIN_STAGE}.source.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        questions = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    out = {}
    for item in items:
        i = item.get("index")
        if isinstance(i, int) and 0 <= i < len(questions) and str(item.get("plain", "")).strip():
            out[questions[i]] = {"plain": str(item["plain"]).strip(), "audience": item.get("audience", "user")}
    return out


def plain_questions(plan: dict, ws: Path | None = None) -> tuple[list[dict], list[dict]]:
    """返回（问提出想法的人的问题, 交给开发者的技术备注），每项 {"text", "original", ...}。"""
    rewrites = load_rewrites(ws) if ws else {}
    users, devs = [], []
    for q in model_questions(plan):
        r = rewrites.get(q)
        item = {"text": r["plain"] if r else q, "original": q}
        (devs if r and r["audience"] == "dev" else users).append(item)
    users += component_questions(plan)
    return users, devs


def rewrite_questions(plan: dict, runner, ws: Path, log: Callable[[str], None] = print) -> None:
    """推导完后调用：把模型写的问题改写成大白话并分流。离线 mock 只做规则分流，不改写。"""
    from blueprint.pipeline import StageRunner, atomic_write
    questions = model_questions(plan)
    ws = Path(ws)
    (ws / "stages").mkdir(parents=True, exist_ok=True)
    result = ws / "stages" / f"{PLAIN_STAGE}.json"
    if not questions:
        atomic_write(result, json.dumps({"items": []}))
    elif getattr(runner, "name", "") == "mock":
        items = [{"index": i, "plain": q, "audience": "dev" if _looks_technical(q) else "user"}
                 for i, q in enumerate(questions)]
        atomic_write(result, json.dumps({"items": items}, ensure_ascii=False, indent=2))
    else:
        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
        stages = StageRunner(runner, ws, resume=True, log=log, context={"kind": "plain"})
        stages.run(PLAIN_STAGE, load_prompt(PLAIN_STAGE).format(questions=numbered), PLAIN_SCHEMA, "⑥ 问题改成大白话")
    # 最后才写编号对应的原问题：改写中途失败时，两个文件仍是上一次的一对，不会错位
    atomic_write(ws / "stages" / f"{PLAIN_STAGE}.source.json", json.dumps(questions, ensure_ascii=False, indent=2))


_TECH_MARKERS = ("组件 s", "特征", "schema", "字段", "标签", "选型", "接口", "工具名")


def _looks_technical(question: str) -> bool:
    return any(m in question for m in _TECH_MARKERS)


def component_label(component_id: str) -> str:
    comp = COMPONENT_BY_ID.get(component_id)
    return f"{component_id} {comp.name}" if comp else component_id
