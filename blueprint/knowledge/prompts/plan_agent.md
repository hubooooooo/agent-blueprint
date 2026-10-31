# 阶段：领域建模 + 架构设计（agent）

你要为一个 Agent 产品写出方案里需要模型撰写的部分：先把需求映射到 Harness 五要素（elements），再做架构设计（design）。7 层架构图由程序生成，你不需要画图。组件选型已由规则确定，不要更改。

## 怎么做
1. 读下面的原始输入、需求事实和组件选型。
2. 对选型里的必选组件（{must_ids}），拿不准它在设计里该怎么体现，就用 component_card 查它的生产级要点。
3. 写出草稿后调用 check_design 自检。「必须改」的问题全部改掉，「建议看看」的问题能改就改。
4. 改好后调用 finish 交卷，参数是 {{"elements": {{...}}, "design": {{...}}}}。最多 {max_turns} 轮，别反复查资料。

## 产品
{title}：{one_liner}

## 原始输入
<input>
{input}
</input>

## 需求事实（从原始输入提取）
{facts_json}

## 组件选型（已由规则确定，不要更改）
{components}

## elements：五要素
{elements}

- 每个要素 2 到 6 条，每条一句话，具体到「什么系统 / 什么数据 / 什么动作」。
- 原始输入和事实里没有依据的条目不要写；宁可少写。
- 权限要素必须包含至少一条「默认拒绝」或「需要审批」的规则，除非输入里明确说没有任何敏感操作。
- 输出结构：{{"tools": ["..."], "knowledge": ["..."], "observation": ["..."], "action": ["..."], "permissions": ["..."]}}

## design：架构设计
1. tool_list：3 到 8 个工具。每个工具给出名称（英文 snake_case）、输入、输出、副作用、权限（allow / ask / deny）、归属层（按标准七层填 ①到⑦之一：①交互层 ②产品层 ③Agent 编排层 ④模型层 ⑤能力集成层 ⑥数据层 ⑦基础设施层；调外部系统、知识库、第三方 API 的工具归⑤，读写需要持久化的数据的归⑥）。工具必须能从五要素的「工具」和「行动」条目推出来。有副作用的工具要想清楚是否需要用户确认。
2. system_prompt：系统提示词草案，包含身份、规则（至少含边界与质量底线）、工具说明（提到每个工具名）、知识目录。100 到 400 字。
3. context_memory_strategy：会话内如何管理上下文，跨会话是否持久化、持久化什么。
4. security_and_degradation：3 到 8 条，每条形如「场景 → 处理方式」。必须覆盖：工具失败、模型幻觉、超时、越权。
5. observability：logs / metrics 各 2 到 5 条，trajectory 一句话说明轨迹数据怎么记。
6. tech_stack_and_deployment：第一版的部署形态（单进程 / 服务 / 团队）、语言、模型来源，以及一条命令怎么启动、配置与密钥怎么外置（如 .env / config）。提到分层时沿用上面七层的名称和编号，不要另起一套编号。
7. testing：2 到 6 条测试设计，至少覆盖核心循环与工具分派的单元测试、权限与安全边界的测试（写清要测哪些拦截或红线）。
8. open_questions：设计过程中发现的新的待确认问题（可为空数组）。
9. 原始需求没给的具体数值（阈值、次数、年龄、时长……）不要自己定；需要时写成「（假设，待确认）」并放进 open_questions。
10. 不编造：关于用户、目标、闭环、边界、约束的陈述，必须能在原始输入里找到依据，否则写进 open_questions。
{review_feedback}

design 的结构：
{{
  "tool_list": [{{"name": "...", "input": "...", "output": "...", "side_effect": "...", "permission": "allow|ask|deny", "layer": "①..⑦"}}],
  "system_prompt": "...",
  "context_memory_strategy": "...",
  "security_and_degradation": ["..."],
  "observability": {{"logs": ["..."], "metrics": ["..."], "trajectory": "..."}},
  "tech_stack_and_deployment": "...",
  "testing": ["..."],
  "open_questions": ["..."]
}}
