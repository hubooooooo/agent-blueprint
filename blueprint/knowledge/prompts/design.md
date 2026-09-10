# 阶段：架构设计

基于需求事实、五要素和已确定的组件选型，产出方案文档中需要模型撰写的部分。7 层架构图由程序生成，你不需要画图。

## 产品
{title}：{one_liner}

## 需求事实
{facts_json}

## 五要素
{elements_json}

## 组件选型（已由规则确定，不要更改）
{components_json}

## 要求
1. tool_list：3 到 8 个工具。每个工具给出名称（英文 snake_case）、输入、输出、副作用、权限（allow / ask / deny）、归属层（①到⑦之一）。工具必须能从五要素的「工具」和「行动」条目推出来。
2. system_prompt：系统提示词草案，包含身份、规则（至少含边界与质量底线）、工具说明、知识目录。100 到 400 字。
3. context_memory_strategy：会话内如何管理上下文，跨会话是否持久化、持久化什么。
4. security_and_degradation：3 到 8 条，每条形如「场景 → 处理方式」。必须覆盖：工具失败、模型幻觉、超时、越权。
5. observability：logs / metrics 各 2 到 5 条，trajectory 一句话说明轨迹数据怎么记。
6. tech_stack_and_deployment：第一版的部署形态（单进程 / 服务 / 团队）、语言、模型来源。
7. open_questions：设计过程中发现的新的待确认问题（可为空数组）。
{review_feedback}

## 输出 JSON 结构
{{
  "tool_list": [{{"name": "...", "input": "...", "output": "...", "side_effect": "...", "permission": "allow|ask|deny", "layer": "①..⑦"}}],
  "system_prompt": "...",
  "context_memory_strategy": "...",
  "security_and_degradation": ["..."],
  "observability": {{"logs": ["..."], "metrics": ["..."], "trajectory": "..."}},
  "tech_stack_and_deployment": "...",
  "open_questions": ["..."]
}}
