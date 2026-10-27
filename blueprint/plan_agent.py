"""方案推导的 agent：一次写出五要素和架构设计，过程中可以查组件说明、用 check_design 自检。

选型已经由规则算好，agent 不能改；check_design 是纯代码规则，把「工具清单与选型对不上」
「降级场景漏写」这类能机械判断的问题在审稿前拦下来，硬性问题不改好不能交卷。
"""

from __future__ import annotations

import json
import re
from typing import Callable

from blueprint.agent import Tool, run_agent
from blueprint.audit_agent import component_card
from blueprint.knowledge import COMPONENT_BY_ID, FIVE_ELEMENTS, load_prompt
from blueprint.pipeline import SYSTEM
from blueprint.schema import DESIGN_SCHEMA, MODEL_SCHEMA

MAX_TURNS = 10
LAYERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

RESULT_SCHEMA = {
    "type": "object",
    "required": ["elements", "design"],
    "properties": {"elements": MODEL_SCHEMA, "design": DESIGN_SCHEMA},
}

# 安全降级必须覆盖的四类场景（审稿标准第 4 条），任一同义词出现即算覆盖
DEGRADATION = {
    # 真实方案里工具失败常写成具体场景（「PDF 解析失败」「审核服务不可用」），不会逐字写「工具失败」
    "工具失败": ("失败", "不可用", "报错", "出错", "异常"),
    "模型幻觉": ("幻觉", "编造", "瞎编", "胡编"),
    "超时": ("超时",),
    "越权": ("越权", "未授权", "无权限", "权限不足", "超出权限"),
}

# 审稿按六条验收标准查，其中「可测试」「可运行」最常因整节缺失被判 high，所以列为必须项
TEST_UNIT = ("单元测试", "单测", "unit")
TEST_BOUNDARY = ("边界", "权限", "安全", "拦截", "越权", "红线")
RUN_START = ("启动", "运行命令", "一条命令", "python ", "npm ", "docker")
RUN_CONFIG = (".env", "config", "配置", "环境变量")
NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:秒|分钟|小时|天|周|次|岁|%|％|页|条|字|ms|MB|KB|GB|元)")

# 必选组件在设计里应该留下的痕迹（只给提醒，不拦交卷）
COMPONENT_HINTS = {
    "s04": ("钩子", "hook", "拦截", "审计"),
    "s05": ("计划", "进度", "todo", "待办"),
    "s06": ("子 agent", "子agent", "subagent", "子任务"),
    "s07": ("按需加载", "技能", "知识库", "检索"),
    "s08": ("压缩", "摘要", "截断"),
    "s09": ("记忆", "跨会话", "持久化"),
    "s10": ("任务", "断点", "续跑"),
    "s11": ("后台", "异步"),
    "s12": ("定时", "cron", "调度"),
    "s13": ("团队", "并行", "worktree"),
    "s14": ("mcp", "插件"),
    "s16": ("工作流", "流水线", "固定流程", "阶段"),
    "s17": ("评估", "验收", "完成判断", "评估器"),
}


def check_design(elements: dict, design: dict, extract: dict, decisions: list[dict],
                 input_text: str = "") -> tuple[list[str], list[str]]:
    """返回 (必须改的问题, 建议看看的提醒)。只做能机械判断的检查，不评价写得好不好。

    input_text：原始输入，用来找设计里出现、但输入没给过的具体数值。
    """
    errors: list[str] = []
    warnings: list[str] = []
    tools = design.get("tool_list") or []
    names = [str(t.get("name", "")) for t in tools]
    if not 3 <= len(tools) <= 8:
        errors.append(f"tool_list 要 3 到 8 个工具，现在 {len(tools)} 个")
    for name in names:
        if not TOOL_NAME.match(name):
            errors.append(f"工具名 {name!r} 不是英文 snake_case")
    for name in {n for n in names if names.count(n) > 1}:
        errors.append(f"工具名 {name} 重复")
    for t in tools:
        if not str(t.get("layer", "")).startswith(LAYERS):
            errors.append(f"工具 {t.get('name')} 的 layer 应为 ①–⑦ 之一，现在是 {t.get('layer')!r}")

    lines = " ".join(design.get("security_and_degradation") or [])
    for scene, words in DEGRADATION.items():
        if not any(w in lines for w in words):
            errors.append(f"security_and_degradation 没覆盖「{scene}」场景")

    destructive = (extract.get("features", {}).get("destructive_ops") or {}).get("value") == "yes"
    if destructive and not any(t.get("permission") in ("ask", "deny") for t in tools):
        errors.append("需求涉及破坏性或敏感操作（destructive_ops=yes），但没有任何工具的权限是 ask 或 deny")
    if destructive and not any(w in " ".join(elements.get("permissions") or []) for w in ("默认拒绝", "审批", "确认")):
        errors.append("权限要素里要有至少一条「默认拒绝」或「需要审批 / 确认」的规则")

    testing = " ".join(design.get("testing") or []).lower()
    if not any(w in testing for w in TEST_UNIT):
        errors.append("testing 要写核心循环与工具分派的单元测试（验收标准「可测试」）")
    if not any(w in testing for w in TEST_BOUNDARY):
        errors.append("testing 要写权限与安全边界的测试，说明测哪些拦截或红线（验收标准「可测试」）")
    deploy = str(design.get("tech_stack_and_deployment", "")).lower()
    if not any(w in deploy for w in RUN_START):
        errors.append("tech_stack_and_deployment 要写一条命令怎么启动（验收标准「可运行」）")
    if not any(w in deploy for w in RUN_CONFIG):
        errors.append("tech_stack_and_deployment 要写配置与密钥怎么外置，如 .env / config（验收标准「可运行」）")

    if input_text:
        made_up = sorted({m.group(0) for m in NUMBER.finditer(json.dumps(design, ensure_ascii=False))
                          if not re.search(rf"(?<![\d.]){re.escape(m.group(1))}(?![\d.])", input_text)})
        if made_up:
            warnings.append("这些数值原始输入里没有：" + "、".join(made_up[:8])
                            + "。如果是你定的，标成「（假设，待确认）」并放进 open_questions")

    prompt = str(design.get("system_prompt", ""))
    if not 100 <= len(prompt) <= 400:
        warnings.append(f"system_prompt 建议 100 到 400 字，现在 {len(prompt)} 字")
    for name in names:
        if name and name not in prompt:
            warnings.append(f"system_prompt 没提到工具 {name}")
    for t in tools:
        effect = str(t.get("side_effect", "")).strip()
        if t.get("permission") == "allow" and effect and not re.search(r"^(无|没有|只读|none)", effect, re.I):
            warnings.append(f"工具 {t.get('name')} 有副作用（{effect}）却是 allow，确认是否不需要用户确认")

    text = json.dumps({"elements": elements, "design": design}, ensure_ascii=False).lower()
    for d in decisions:
        hints = COMPONENT_HINTS.get(d["id"])
        if d["decision"] == "必选" and hints and not any(h.lower() in text for h in hints):
            warnings.append(f"选型里 {d['id']} {d['name']} 是必选，但设计里没看到对应安排")
    return errors, warnings


def _report(errors: list[str], warnings: list[str]) -> str:
    out = []
    if errors:
        out.append("必须改（不改不能交卷）：\n- " + "\n- ".join(errors))
    if warnings:
        out.append("建议看看（不拦交卷）：\n- " + "\n- ".join(warnings))
    return "\n\n".join(out) or "没有发现问题，可以交卷。"


def run_design_agent(input_text: str, extract: dict, decisions: list[dict], runner, review_feedback: str = "",
                     log: Callable[[str], None] = print, max_turns: int = MAX_TURNS) -> dict:
    """返回 {"elements": 五要素, "design": 架构设计}。失败抛 AgentFailed 或模型调用异常，由调用方退回固定流程。"""
    def check_tool(args: dict) -> str:
        return _report(*check_design(args.get("elements") or {}, args.get("design") or {}, extract, decisions,
                                     input_text))

    def finish_check(result: dict) -> list[str]:
        return check_design(result["elements"], result["design"], extract, decisions, input_text)[0]

    tools = [
        Tool("component_card", "查某个 Harness 组件（s01–s17）是什么、什么时候需要、生产级要点。", {
            "type": "object", "required": ["id"], "properties": {"id": {"type": "string", "description": "如 s03"}}},
            component_card),
        Tool("check_design", "交卷前自检：传入草稿（elements 和 design），返回必须改的问题和建议看看的提醒。", {
            "type": "object", "required": ["elements", "design"],
            "properties": {"elements": {"type": "object"}, "design": {"type": "object"}}},
            check_tool),
    ]
    prompt = load_prompt("plan_agent").format(
        title=extract["title"], one_liner=extract.get("one_liner", ""), input=input_text,
        facts_json=json.dumps(extract["facts"], ensure_ascii=False, indent=2),
        elements="\n".join(f"- {k}：{v}" for k, v in FIVE_ELEMENTS.items()),
        components="\n".join(f"- {d['id']} {d['name']}：{d['decision']}（{d['reason']}）" for d in decisions),
        must_ids="、".join(d["id"] for d in decisions if d["decision"] == "必选"
                          and not COMPONENT_BY_ID[d["id"]].always) or "（无）",
        review_feedback=review_feedback, max_turns=max_turns)
    return run_agent("design_agent", SYSTEM, prompt, tools, RESULT_SCHEMA, runner, log=log, max_turns=max_turns,
                     check=finish_check, describe=_describe,
                     finish_description="写完并自检后调用，提交五要素（elements）和架构设计（design）。"
                                        "必须改的问题没改好会被退回。")


def _describe(name: str, args: dict) -> str:
    if name == "component_card":
        return f"查组件说明 {args.get('id', '')}"
    if name == "check_design":
        return "自检设计草稿"
    return name
