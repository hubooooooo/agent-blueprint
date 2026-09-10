"""引擎的"尺子"：五要素、17 个组件、特征表、8 问、6 条验收标准。

正向用它来填表，反向用它来核对。所有可判定的规则都写在这里，不交给模型猜。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 五要素
# ---------------------------------------------------------------------------

FIVE_ELEMENTS = {
    "tools": "工具：交付物需要什么外部动作（查询、写入、调用、发送）",
    "knowledge": "知识：领域专长从哪来（文档、schema、业务规则）",
    "observation": "观察：如何确认动作产生了预期效果（日志、diff、状态）",
    "action": "行动：动作以什么形式执行（API、CLI、UI、消息）",
    "permissions": "权限：哪些动作需要审批，哪些数据不能碰",
}

# ---------------------------------------------------------------------------
# 需求硬事实（Step 1 的六个维度）
# ---------------------------------------------------------------------------

FACT_KEYS = {
    "goal": "目标：产品要完成什么？可量化的成功标准是什么？",
    "users": "用户：谁在用？人机比？同步还是异步？",
    "core_loop": "核心闭环：一次完整的「输入 → Agent 行为 → 交付物」",
    "deliverable": "交付物：代码、文档、决策、操作，还是别的？",
    "boundaries": "边界：明确不能做什么？",
    "constraints": "约束：时延、并发、合规、成本、可用模型",
}

# 小白指南的 8 个问题，用于补全需求 / 生成待确认清单
EIGHT_QUESTIONS = [
    "要达成什么？一句话说清产品目标，以及怎样算做成。",
    "给谁用？目标用户、使用频率、同步还是异步交互。",
    "一次完整交付长什么样？从用户输入到交付物的完整闭环。",
    "需要什么外部动作？必须调用的系统、API、数据源。",
    "领域知识在哪？模型必须知道的规则、文档、schema。",
    "什么绝对不能做？安全红线、数据边界、合规约束。",
    "失败怎么办？工具失败、模型幻觉、超时、越权时的降级策略。",
    "怎么算成功？可度量的指标（完成率、时延、成本、准确率）。",
]

# ---------------------------------------------------------------------------
# 特征 → 组件（BLUEPRINT 第四节的映射表）
# ---------------------------------------------------------------------------

FEATURE_VALUES = ("yes", "no", "later", "unknown")


@dataclass(frozen=True)
class Feature:
    id: str
    question: str          # 让模型回答的问题
    component: str         # 触发的组件 id


FEATURES: list[Feature] = [
    Feature("destructive_ops", "是否涉及破坏性或敏感操作（删除、写入外部系统、支付、发送消息、隐私数据）？", "s03"),
    Feature("audit_needed", "是否需要审计、拦截、埋点、合规记录？", "s04"),
    Feature("multi_step", "单次交付是否多步骤、需要跟踪进度？", "s05"),
    Feature("context_heavy", "是否会出现上下文爆炸的子任务，或可并行的探索型子任务？", "s06"),
    Feature("large_knowledge", "领域知识库是否庞大、需要按需加载？", "s07"),
    Feature("long_sessions", "会话是否很长、工具输出或日志量是否很大？", "s08"),
    Feature("cross_session_memory", "是否需要跨会话记住用户偏好、决策、历史？", "s09"),
    Feature("persistent_goals", "目标是否需要持久化、支持断点续跑？", "s10"),
    Feature("slow_operations", "是否有耗时几分钟以上的慢操作需要不阻塞主流程？", "s11"),
    Feature("scheduled", "是否需要定时自动触发？", "s12"),
    Feature("parallel_isolated", "是否需要多任务并行且各自隔离工作区（多 Agent 团队）？", "s13"),
    Feature("external_ecosystem", "是否需要接入外部工具生态（MCP、第三方插件）？", "s14"),
    Feature("fixed_orchestration", "编排形态是否固定、适合写死成工作流？", "s16"),
    Feature("auto_completion", "是否需要自动判断「何时算完成」（独立评估器）？", "s17"),
]

FEATURE_BY_ID = {f.id: f for f in FEATURES}


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    domain: str
    one_liner: str
    when: str
    production_points: str
    readme: str
    signals: tuple[str, ...] = field(default_factory=tuple)   # 反向扫描用的正则
    always: bool = False


COMPONENTS: list[Component] = [
    Component("s01", "Agent Loop", "行动域", "最小可运行闭环",
              "一切基础：循环 + 工具",
              "重试、超时、token 上限、stop_reason 完整处理",
              "s01_agent_loop/README.md",
              (r"tool_use", r"tool_calls", r"messages\.create", r"chat\.completions", r"function_call", r"agent_loop", r"while\s+True"),
              always=True),
    Component("s02", "工具系统", "行动域", "循环不变，工具可增",
              "需要调用外部系统/API/数据源",
              "JSON schema 严格、参数校验、错误回传格式统一",
              "s02_tool_use/README.md",
              (r"input_schema", r"TOOL_HANDLERS", r"\"parameters\"\s*:", r"def run_\w+\(", r"@tool", r"tools\s*=\s*\["),
              always=True),
    Component("s03", "权限系统", "约束域", "先划边界，再给自由",
              "涉及破坏性/敏感操作",
              "白名单/黑名单、破坏性操作二次确认、审计日志、默认拒绝",
              "s03_permission/README.md",
              (r"permission", r"DENY_LIST", r"allow.?list", r"deny", r"check_permission", r"is_relative_to", r"safe_path")),
    Component("s04", "钩子系统", "约束域", "挂循环上，不写循环里",
              "需要审计、拦截、埋点",
              "PreToolUse 可阻断、PostToolUse 可观察、异常不影响主循环",
              "s04_hooks/README.md",
              (r"PreToolUse", r"PostToolUse", r"register_hook", r"trigger_hooks", r"\bhooks?\b", r"middleware", r"interceptor")),
    Component("s05", "任务规划", "认知域", "先计划后执行",
              "多步骤、需跟踪进度",
              "计划持久化、状态流转、进度可查询",
              "s05_todo_write/README.md",
              (r"todo_write", r"TodoManager", r"\btodos?\b", r"plan(?:ning)?_step", r"checklist")),
    Component("s06", "子 Agent", "上下文域", "全新消息列表，隔离噪声",
              "上下文会爆、任务可并行",
              "独立消息列表、最终文本回传、超时回收",
              "s06_subagent/README.md",
              (r"subagent", r"sub_agent", r"spawn_subagent", r"run_subagent", r"delegate", r"child_agent")),
    Component("s07", "技能加载", "认知域", "用到时再加载",
              "领域知识库庞大",
              "目录先行、按需展开、版本管理",
              "s07_skill_loading/README.md",
              (r"SKILL\.md", r"load_skill", r"SkillLoader", r"skills_dir", r"knowledge_base", r"\brag\b", r"retriev")),
    Component("s08", "上下文压缩", "上下文域", "长上下文腾空间",
              "长会话、日志量大",
              "分层压缩、先裁工具结果再摘要历史、保留权威指令",
              "s08_context_compact/README.md",
              (r"compact", r"summariz", r"truncat", r"context_window", r"micro_compact", r"prompt_too_long")),
    Component("s09", "记忆系统", "认知域", "记住该记的，忘掉该忘的",
              "需跨会话记住偏好/决策",
              "筛选→提取→整合三子系统、持久化 + 检索、冲突时用户指令优先",
              "s09_memory/README.md",
              (r"MEMORY\.md", r"\.memory", r"memor(?:y|ies)", r"remember", r"consolidate")),
    Component("s10", "任务系统", "协作域", "大目标拆小任务，持久化",
              "目标需持久化、断点续跑",
              "文件持久化、依赖图、原子状态变更、并发锁",
              "s10_task_system/README.md",
              (r"TaskStore", r"blockedBy", r"\.tasks/", r"claim_task", r"complete_task", r"task_graph")),
    Component("s11", "后台任务", "协作域", "慢操作丢后台",
              "有慢操作需不阻塞",
              "线程池、完成通知注入、超时与清理",
              "s11_background_tasks/README.md",
              (r"run_in_background", r"BackgroundManager", r"threading\.Thread", r"task_notification", r"asyncio\.create_task", r"celery", r"queue")),
    Component("s12", "定时调度", "协作域", "到点自动触发",
              "需定时自治触发",
              "持久化调度、幂等、会话级作用域",
              "s12_cron_scheduler/README.md",
              (r"\bcron\b", r"schedule", r"scheduled_tasks", r"apscheduler", r"every\s+\d+", r"interval")),
    Component("s13", "Agent 团队", "协作域", "队友分工协作",
              "多任务并行、需隔离工作区",
              "原子认领、任务绑定 worktree、异步邮箱、类型化协议、关停流程",
              "s13_agent_teams/README.md",
              (r"teammate", r"worktree", r"MessageBus", r"\.mailboxes", r"spawn_teammate", r"crew", r"swarm")),
    Component("s14", "MCP 插件", "行动域", "外部工具接入同一工具池",
              "需接入外部工具生态",
              "工具发现、mcp__server__tool 命名空间、连接失败降级",
              "s14_mcp_plugin/README.md",
              (r"\bmcp\b", r"mcp__", r"MCPClient", r"connect_mcp", r"tools/list", r"tools/call", r"plugin")),
    Component("s15", "集成 Harness", "编排域", "多机制归一循环",
              "上述机制需协同（选了 3 个以上可选组件）",
              "单一循环、动态重建系统提示词、共享客户端、跨模块状态协调",
              "s15_integrated_harness/README.md",
              (r"assemble_system_prompt", r"assemble_tool_pool", r"integrated", r"harness")),
    Component("s16", "工作流运行时", "编排域", "编排形状固定就写进代码",
              "编排形态固定",
              "脚本拥有编排、生命周期事件、journal 断点续跑",
              "s16_workflow_runtime/README.md",
              (r"workflow", r"journal", r"pipeline\(", r"WorkflowRunner", r"langgraph", r"state_machine", r"\bdag\b")),
    Component("s17", "目标闭环", "认知域", "目标决定循环何时停止",
              "需自动判断「何时算完成」",
              "独立评估器、目标不可能/失败/超限时交还控制权",
              "s17_goal_loop/README.md",
              (r"goal", r"evaluator", r"judge", r"acceptance", r"verify_done", r"is_complete", r"stop_hook")),
]

COMPONENT_BY_ID = {c.id: c for c in COMPONENTS}
OPTIONAL_COMPONENT_IDS = [c.id for c in COMPONENTS if not c.always and c.id != "s15"]

# ---------------------------------------------------------------------------
# 6 条验收标准
# ---------------------------------------------------------------------------

ACCEPTANCE = {
    "runnable": ("可运行", "一条命令能起，配置与密钥外置（.env / config）"),
    "fault_tolerant": ("可容错", "工具失败、模型幻觉、超时、越权都有明确降级路径"),
    "observable": ("可观测", "有日志、有指标、有轨迹数据"),
    "testable": ("可测试", "核心循环与工具分派有单测，权限与安全有边界测试"),
    "deployable": ("可部署", "有明确的部署形态（单进程 / 服务 / 团队）与启动文档"),
    "measurable": ("可度量", "有对齐 PRD 的成功指标，并能采集"),
}

# 7 层架构
LAYERS = [
    ("①", "交互层", "谁在用、怎么用？", "CLI / Web / App / API；同步或异步；人机比"),
    ("②", "产品层", "产品外壳是什么？", "会话管理、请求路由、账户、业务逻辑"),
    ("③", "Agent 编排层", "Harness 如何运转？", "loop、工具分发、hooks、权限、记忆、任务、技能、压缩、子 agent / 团队、目标闭环"),
    ("④", "模型层", "智能从哪来？", "主模型、辅助模型、路由、fallback、成本"),
    ("⑤", "能力集成层", "如何触达外部世界？", "内部工具、MCP server、知识库、第三方 API"),
    ("⑥", "数据层", "什么需要持久化？", "记忆、任务、会话历史、轨迹数据、日志指标"),
    ("⑦", "基础设施层", "如何部署运行？", "单进程 / 服务 / 团队、沙箱、队列、调度、监控"),
]
