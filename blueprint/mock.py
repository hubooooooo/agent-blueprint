"""离线 Mock Runner：不花钱，用关键词启发式产出结构合法的阶段输出。

用途：测试、evals 的管线回归、没有 API key 时的演示。
它不追求判断准确，只保证每个阶段的输出结构与真实模型一致。
"""

from __future__ import annotations

import re

from blueprint.knowledge import FEATURES

_FEATURE_KEYWORDS: dict[str, list[str]] = {
    "destructive_ops": ["删除", "写入", "修改", "发送", "支付", "退款", "部署", "隐私", "照片", "敏感",
                        "delete", "deploy", "refund", "privacy", "photo"],
    "audit_needed": ["审计", "审核", "拦截", "埋点", "合规", "audit", "compliance"],
    "multi_step": ["多步", "步骤", "进度", "阶段", "分幕", "multi-step", "计划"],
    "context_heavy": ["并行", "大量文件", "长文档", "论文", "30 页", "30页", "探索", "parallel", "explore", "代码库"],
    "large_knowledge": ["知识库", "规范", "术语", "文档库", "领域知识", "规则库", "范式", "glossary"],
    "long_sessions": ["长会话", "长时间", "大量日志", "长对话", "long session"],
    "cross_session_memory": ["记住", "偏好", "跨会话", "个性化", "历史记录", "积累", "remember", "preference"],
    "persistent_goals": ["断点", "续跑", "持久化", "长期目标", "resume"],
    "slow_operations": ["几分钟", "耗时", "异步", "后台", "慢操作", "background"],
    "scheduled": ["定时", "每天", "每周", "每小时", "每晚", "cron", "daily", "weekly", "nightly"],
    "parallel_isolated": ["团队", "多 agent", "多个 agent", "多agent", "worktree", "多人协作", "swarm"],
    "external_ecosystem": ["mcp", "第三方工具", "插件", "plugin", "工具生态"],
    "fixed_orchestration": ["固定流程", "固定顺序", "固定编排", "fixed pipeline"],
    "auto_completion": ["自动判断", "算不算合格", "验收", "达标", "是否完成", "quality gate", "评估器"],
}

_LATER_MARKERS = ["二期", "以后", "未来", "后续", "later", "phase 2", "v2"]


def _guess_features(text: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    low = text.lower()
    for feat in FEATURES:
        hits = [w for w in _FEATURE_KEYWORDS.get(feat.id, []) if w.lower() in low]
        if not hits:
            result[feat.id] = {"value": "unknown", "evidence": "输入未提及"}
            continue
        value = "yes"
        for h in hits:
            idx = low.find(h.lower())
            window = low[max(0, idx - 40): idx + 40]
            if any(m in window for m in _LATER_MARKERS):
                value = "later"
                break
        result[feat.id] = {"value": value, "evidence": "关键词命中：" + "、".join(hits[:3])}
    return result


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:60]
    return "未命名产品"


def _fact(text: str, keys: list[str]) -> dict:
    for line in text.splitlines():
        if any(k in line for k in keys):
            value = re.sub(r"^[\s|#*\-]+", "", line).strip()
            return {"value": value[:200], "status": "明确", "source": value[:80]}
    return {"value": "", "status": "待确认", "source": ""}


class MockRunner:
    name = "mock"

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, stage: str, system: str, prompt: str, schema: dict) -> dict:
        self.calls.append(stage)
        stage = stage.removesuffix("_retry")
        if stage in ("extract", "infer"):
            return self._extract(prompt, stage)
        if stage == "model":
            return {
                "tools": ["按输入推断的查询类工具", "按输入推断的写入类工具"],
                "knowledge": ["领域规则与术语（待补充来源）"],
                "observation": ["工具返回状态", "生成耗时"],
                "action": ["API 调用", "结构化文本输出"],
                "permissions": ["写入与删除类操作默认需要审批", "越出工作目录的路径一律拒绝"],
            }
        if stage == "design":
            return {
                "tool_list": [
                    {"name": "fetch_input", "input": "用户输入", "output": "结构化内容", "side_effect": "无",
                     "permission": "allow", "layer": "⑤"},
                    {"name": "generate_output", "input": "结构化内容", "output": "交付物", "side_effect": "无",
                     "permission": "allow", "layer": "③"},
                    {"name": "save_result", "input": "交付物", "output": "存储确认", "side_effect": "写存储",
                     "permission": "ask", "layer": "⑥"},
                ],
                "system_prompt": "你是本产品的 Agent。规则：1. 不越界；2. 不编造；3. 完成后总结。工具：fetch_input、generate_output、save_result。知识目录：领域规则。",
                "context_memory_strategy": "会话内保留完整消息；跨会话默认不持久化（mock）。",
                "security_and_degradation": [
                    "工具失败 → 返回错误文本给模型并重试一次",
                    "模型幻觉 → 输出前过独立校验",
                    "超时 → 120 秒后中断并提示用户",
                    "越权 → 默认拒绝并记录审计日志",
                ],
                "observability": {"logs": ["每次工具调用", "每轮耗时"], "metrics": ["成功率", "平均时延"],
                                  "trajectory": "JSONL 记录每一步"},
                "tech_stack_and_deployment": "第一版单进程 Python；模型来自 .env 配置。",
                "open_questions": [],
            }
        if stage in ("review", "audit_review"):
            return {"ok": True, "score": 80, "issues": [], "summary": "mock 审稿：结构完整，未做语义判断。"}
        raise ValueError(f"mock 不认识的阶段：{stage}")

    def _extract(self, prompt: str, stage: str) -> dict:
        tag = "input" if stage == "extract" else "readme"
        m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", prompt, re.S)
        text = m.group(1) if m else prompt
        facts = {
            "goal": _fact(text, ["目标", "帮", "解决", "goal"]),
            "users": _fact(text, ["用户", "给谁", "家长", "学生", "工程师", "产品经理", "user"]),
            "core_loop": _fact(text, ["闭环", "流程", "→", "->", "步骤"]),
            "deliverable": _fact(text, ["交付", "输出", "产出", "生成", "报告", "脚本"]),
            "boundaries": _fact(text, ["不能", "禁止", "红线", "边界", "不得"]),
            "constraints": _fact(text, ["约束", "时延", "成本", "模型", "合规", "秒", "分钟"]),
        }
        unknowns = [k for k, v in facts.items() if v["status"] == "待确认"]
        data = {
            "title": _first_line(text),
            "one_liner": _first_line(text),
            "facts": facts,
            "features": _guess_features(text),
            "unknowns": [f"请补充：{k}" for k in unknowns],
        }
        if stage == "infer":
            data["product_summary"] = "mock 推断：" + _first_line(text)
        return data
