# 阶段：需求拆解

从下面的输入（一个点子、一段描述、或一份不完整的 PRD）里提取硬事实，并回答特征问题。

## 要提取的六个维度
{fact_keys}

每个维度输出 {{"value": 结论, "status": "明确" 或 "待确认", "source": 输入原文的引用或空字符串}}。
输入里没有的，value 写你能给出的最保守推断或空字符串，status 必须是「待确认」。

## 特征问题（决定选用哪些组件）
{features}

每个特征输出 {{"value": "yes" | "no" | "later" | "unknown", "evidence": 一句话依据}}。
features 的键必须是上面列出的 feature_id（如 destructive_ops），**不要用组件编号（如 s03）作键**，14 个特征一个都不能少。
- yes：输入明确需要，或产品闭环里必然包含（例如触碰用户照片、身份、支付等隐私/敏感数据，destructive_ops 就是 yes）
- later：输入里有「未来 / 二期 / 以后再做」这类原文依据，第一版可以不做；没有原文依据不要写 later
- no：输入已经把产品闭环说清楚，而这个特征不在闭环里、也与产品形态明显无关
- unknown：只在输入信息不足、确实无法判断时使用；不要因为「输入没逐字提到」就写 unknown——
  如果一个单人、单次、同步的产品闭环已经写明，定时调度、多 Agent 团队、外部插件生态这类特征应判 no 而不是 unknown

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
