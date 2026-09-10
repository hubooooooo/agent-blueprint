# 阶段：需求拆解

从下面的输入（一个点子、一段描述、或一份不完整的 PRD）里提取硬事实，并回答特征问题。

## 要提取的六个维度
{fact_keys}

每个维度输出 {{"value": 结论, "status": "明确" 或 "待确认", "source": 输入原文的引用或空字符串}}。
输入里没有的，value 写你能给出的最保守推断或空字符串，status 必须是「待确认」。

## 特征问题（决定选用哪些组件）
{features}

每个特征输出 {{"value": "yes" | "no" | "later" | "unknown", "evidence": 一句话依据}}。
- yes：输入明确需要
- later：输入暗示未来需要、但第一版可以不做
- no：输入明确不需要，或与产品形态明显无关
- unknown：输入没提、无法判断

## 待确认清单
对照下面 8 个问题，输入没有回答的，写成向用户提问的句子放进 unknowns：
{questions}

## 输出 JSON 结构
{{
  "title": "产品名或一句话定位",
  "one_liner": "一句话说清：给谁用、解决什么痛点、得到什么",
  "facts": {{"goal": {{...}}, "users": {{...}}, "core_loop": {{...}}, "deliverable": {{...}}, "boundaries": {{...}}, "constraints": {{...}}}},
  "features": {{"<feature_id>": {{"value": "...", "evidence": "..."}}, ...}},
  "unknowns": ["...", "..."]
}}

## 输入
<input>
{input}
</input>
