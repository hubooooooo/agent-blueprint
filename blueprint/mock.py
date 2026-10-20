"""离线 Mock Runner：不花钱，用关键词启发式产出结构合法的阶段输出。

用途：测试、evals 的管线回归、没有 API key 时的演示。
它不追求判断准确，只保证每个阶段的输出结构与真实模型一致。
"""

from __future__ import annotations

import re

from blueprint.knowledge import FEATURES

# 关键词分两档。强信号：单独命中即判 yes。弱信号：至少命中两个不同的词才判 yes，
# 只命中一个判 unknown（落到「待确认」）。这样 mock 的偏差方向是「宁可少选」，
# 拿不准的留给人确认，而不是把所有沾边的组件都标成必选。
_STRONG_KEYWORDS: dict[str, list[str]] = {
    "destructive_ops": ["删除", "支付", "退款", "部署", "隐私", "敏感数据",
                        "delete", "deploy", "refund", "privacy"],
    "audit_needed": ["审计", "审核", "合规", "埋点", "audit", "compliance"],
    "multi_step": ["多步", "多步骤", "分步执行", "multi-step"],
    "context_heavy": ["大量文件", "长文档", "整个代码库", "整个仓库", "上下文爆炸"],
    "large_knowledge": ["知识库", "术语库", "规则库", "文档库", "领域知识", "glossary", "knowledge base"],
    "long_sessions": ["长会话", "长对话", "大量日志", "long session"],
    "cross_session_memory": ["记住", "跨会话", "偏好", "remember", "preference"],
    "persistent_goals": ["断点续跑", "续跑", "长期目标", "resume"],
    "slow_operations": ["几分钟", "慢操作", "后台执行", "异步执行", "background job"],
    "scheduled": ["定时", "每天", "每周", "每小时", "每晚", "cron", "daily", "weekly", "nightly"],
    "parallel_isolated": ["多 agent", "多个 agent", "多agent", "agent 团队", "worktree", "swarm"],
    "external_ecosystem": ["mcp", "第三方工具", "插件", "plugin", "工具生态"],
    "fixed_orchestration": ["固定流程", "固定顺序", "固定编排", "fixed pipeline"],
    "auto_completion": ["自动判断", "算不算合格", "评估器", "quality gate"],
}
_WEAK_KEYWORDS: dict[str, list[str]] = {
    "destructive_ops": ["写入", "修改", "发送", "上传", "照片", "敏感"],
    "audit_needed": ["拦截", "留痕", "记录"],
    "multi_step": ["步骤", "进度", "阶段", "流程", "计划"],
    "context_heavy": ["并行", "论文", "30 页", "30页", "探索", "代码库", "parallel", "explore"],
    "large_knowledge": ["规范", "术语", "范式", "文档"],
    "long_sessions": ["长时间", "持续运行"],
    "cross_session_memory": ["个性化", "历史记录", "积累", "跨篇", "词库"],
    "persistent_goals": ["持久化", "断点", "恢复"],
    "slow_operations": ["耗时", "异步", "后台", "卡住"],
    "scheduled": ["定期", "自动跑"],
    "parallel_isolated": ["团队", "多人协作", "并行"],
    "external_ecosystem": ["集成", "接入"],
    "fixed_orchestration": ["流水线", "编排", "pipeline"],
    "auto_completion": ["验收", "达标", "是否完成"],
}
# 兼容旧名字：合并后的全部关键词（测试或外部代码可能引用）
_FEATURE_KEYWORDS: dict[str, list[str]] = {
    fid: _STRONG_KEYWORDS.get(fid, []) + _WEAK_KEYWORDS.get(fid, []) for fid in _STRONG_KEYWORDS
}

_LATER_MARKERS = ["二期", "以后", "未来", "后续", "later", "phase 2", "v2"]


def _hits(text_low: str, words: list[str]) -> list[str]:
    return [w for w in words if w.lower() in text_low]


# 按「分句」切：句号/分号/问叹号/换行之外，逗号和冒号也切开，这样「现在要记住偏好，未来再做个性化」
# 里的「记住偏好」不会被同一句后半段的「未来」误染成二期。顿号不切，保持「A、B（二期）」为一个单位。
_CLAUSE_SPLIT = re.compile(r"[。；;！!？?\n，,：:]")


def _is_later(text_low: str, hits: list[str]) -> bool:
    """只有当每个命中词所在的分句都带「二期 / 未来」类标记时才判 later；有任何一处是「现在要」就判 yes。"""
    clauses = [c for c in _CLAUSE_SPLIT.split(text_low) if c.strip()]
    containing = [c for c in clauses if any(h.lower() in c for h in hits)]
    if not containing:
        return False
    return all(any(m in c for m in _LATER_MARKERS) for c in containing)


def _guess_features(text: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    low = text.lower()
    for feat in FEATURES:
        strong = _hits(low, _STRONG_KEYWORDS.get(feat.id, []))
        weak = _hits(low, _WEAK_KEYWORDS.get(feat.id, []))
        if not strong and not weak:
            result[feat.id] = {"value": "unknown", "evidence": "输入未提及"}
            continue
        if not strong and len(weak) < 2:
            result[feat.id] = {"value": "unknown",
                               "evidence": f"仅命中弱信号「{weak[0]}」，不足以判定，待确认"}
            continue
        hits = strong + weak
        value = "later" if _is_later(low, hits) else "yes"
        label = "关键词命中：" + "、".join(hits[:3])
        if not strong:
            label += "（弱信号叠加）"
        result[feat.id] = {"value": value, "evidence": label}
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
