# 阶段：反推项目意图

下面是一个已有代码项目的 README、目录结构和程序扫描出的线索。请反推这个项目**想做什么**，按需求拆解的格式输出。

## 要提取的六个维度
{fact_keys}

每个维度输出 {{"value": 结论, "status": "明确" 或 "待确认", "source": 文件名或原文引用}}。

## 特征问题（判断这类产品应该需要哪些机制；注意是「应该需要」，不是「已经实现」）
{features}

每个特征输出 {{"value": "yes" | "no" | "later" | "unknown", "evidence": 一句话依据}}。

## 待确认清单
项目材料没有回答的问题，写成向项目作者提问的句子。

## 输出 JSON 结构
{{
  "title": "项目名",
  "one_liner": "一句话说清它给谁用、解决什么、产出什么",
  "product_summary": "三到五句话描述这个项目现在的样子",
  "facts": {{"goal": {{...}}, "users": {{...}}, "core_loop": {{...}}, "deliverable": {{...}}, "boundaries": {{...}}, "constraints": {{...}}}},
  "features": {{"<feature_id>": {{"value": "...", "evidence": "..."}}, ...}},
  "unknowns": ["..."]
}}

## README
<readme>
{readme}
</readme>

## 目录结构（截断）
<tree>
{tree}
</tree>

## 程序扫描线索
{inventory_json}
