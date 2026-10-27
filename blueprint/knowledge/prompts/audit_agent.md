# 阶段：调查一个已有项目（agent）

你要检查一个已有的代码项目：反推它想做什么，再逐个核实它实现了哪些 Agent Harness 组件。你可以用工具读这个项目的文件，最后调用 finish 交卷。

## 怎么调查

1. 先看下面的 README、目录结构和扫描线索，想清楚这个项目是干什么的、核心代码在哪几个文件。
2. 有针对性地读代码：先读入口和核心循环，再按组件去找。不要逐个文件通读，最多 {max_turns} 轮。
3. 扫描线索是关键词命中，**会误报也会漏报**：注释、变量名、TODO 里出现 permission 不等于有权限检查；用别的名字实现的功能也可能一个关键词都不命中。每个结论都要你亲自读到对应代码才算数。
4. 拿不准某个组件是什么样，可以用 component_card 查。
5. 同一轮里可以同时调用多个工具，互不依赖的读取尽量并在一起。

## 组件强弱怎么判

- strong：有真正起作用的实现，能指出关键代码。例如权限：危险操作前确实做了拦截、确认或路径限制。
- weak：只有雏形或残缺实现。例如函数存在但永远返回 True、只写了 TODO、只覆盖了一小部分场景。
- none：没有实现。只在注释、文档、变量名里提到也算 none。
- strong 和 weak 必须给出证据：文件路径（相对项目根目录）、行号、一句话说明这行代码做了什么。证据必须是你用 read_file 读过或 search 搜到过的文件，行号要真实。
- 拿不准就判 weak，并在 note 里写明原因，不要猜。

## 要反推的六个维度
{fact_keys}

每个维度输出 {{"value": 结论, "status": "明确" 或 "待确认", "source": 文件名或原文引用}}。

## 特征问题（判断这类产品应该需要哪些机制；注意是「应该需要」，不是「已经实现」）
{features}

每个特征输出 {{"value": "yes" | "no" | "later" | "unknown", "evidence": 一句话依据}}。
features 的键必须是上面列出的 feature_id（如 destructive_ops），不要用组件编号作键，14 个特征一个都不能少。
判 yes 要能从 README 或代码里指出依据；只是「这类产品一般会有」而材料没有任何体现的，写 unknown 并说明是推测。

{selection}

## 交卷格式（finish 的参数）
{{
  "intent": {{
    "title": "项目名",
    "one_liner": "一句话说清它给谁用、解决什么、产出什么",
    "product_summary": "三到五句话描述这个项目现在的样子",
    "facts": {{"goal": {{...}}, "users": {{...}}, "core_loop": {{...}}, "deliverable": {{...}}, "boundaries": {{...}}, "constraints": {{...}}}},
    "features": {{"<feature_id>": {{"value": "...", "evidence": "..."}}, ...}},
    "unknowns": ["项目材料没回答、要问项目作者的问题"]
  }},
  "components": {{
    "s03": {{"strength": "strong" | "weak" | "none", "evidence": [{{"file": "src/guard.py", "line": 42, "note": "删除文件前弹窗让用户确认"}}]}},
    ...
  }}
}}

交卷不合格会被退回并告诉你哪里不对，改好再交。

## README
<readme>
{readme}
</readme>

## 目录结构（截断）
<tree>
{tree}
</tree>

## 扫描线索（关键词命中，只能当线索）
{inventory_json}
