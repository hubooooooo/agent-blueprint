"""把结构化结果渲染成 Markdown 文档。7 层架构图由代码生成，不交给模型画。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from blueprint.knowledge import ACCEPTANCE, COMPONENT_BY_ID, FACT_KEYS, FIVE_ELEMENTS, LAYERS
from blueprint.rules import describe_feature

if TYPE_CHECKING:
    from blueprint.forward import Plan

_FACT_LABEL = {k: v.split("：")[0] for k, v in FACT_KEYS.items()}
_ELEMENT_LABEL = {k: v.split("：")[0] for k, v in FIVE_ELEMENTS.items()}


def _cell(text) -> str:
    return str(text or "").replace("|", "／").replace("\n", " ").strip()


def _components_in_layer3(components: list[dict]) -> str:
    chosen = [d for d in components if d["decision"] == "必选"]
    return " + ".join(f"{d['id']} {d['name']}" for d in chosen) or "loop + 工具"


def architecture_nodes(components: list[dict], tool_list: list[dict], deployment: str) -> list[tuple[str, str]]:
    return [
        ("① 交互层", "CLI / Web / App · 同步或异步（按需求确认）"),
        ("② 产品层", "会话管理 · 请求路由 · 业务逻辑"),
        ("③ Agent 编排层", _components_in_layer3(components)),
        ("④ 模型层", "主模型 · fallback · 成本控制"),
        ("⑤ 能力集成层", "、".join(t["name"] for t in tool_list if t.get("layer") in ("⑤", "5")) or "领域工具"),
        ("⑥ 数据层", "、".join(t["name"] for t in tool_list if t.get("layer") in ("⑥", "6")) or "会话历史 · 轨迹数据 · 日志指标"),
        ("⑦ 基础设施层", deployment or "部署形态待确认"),
    ]


def render_mermaid(title: str, components: list[dict], tool_list: list[dict],
                   facts: dict, deployment: str) -> str:
    def escape(text: str) -> str:
        return (_cell(text).replace("&", "#38;").replace('"', "#34;")
                .replace("<", "#60;").replace(">", "#62;"))

    users = _cell(facts.get("users", {}).get("value")) or "用户（待确认）"
    lines = ["```mermaid", "flowchart TD", f'    U["{escape(users[:60])}"] -->|输入 / 阅读交付物| L1']
    for i, (name, detail) in enumerate(architecture_nodes(components, tool_list, deployment), 1):
        lines.append(f'    L{i}["{escape(name)}<br/>{escape(detail)}"]')
    lines += ["    L1 --> L2", "    L2 --> L3", "    L3 <--> L4", "    L3 --> L5", "    L5 --> L6",
              "    L5 -.->|部署于| L7", "    L6 -.->|部署于| L7", "    subgraph 横切关注点",
              '        SEC["安全边界：权限审批 · 数据红线 · 审计"]',
              '        OBS["可观测性：日志 · 指标 · 轨迹"]', "    end", "```"]
    return "\n".join(lines)


def render_plan(plan: "Plan") -> str:
    ex = plan.extract
    facts = ex.get("facts", {})
    features = ex.get("features", {})
    design = plan.design
    review = plan.review
    out: list[str] = []
    w = out.append

    w(f"# PRD 推导方案 ——「{plan.title}」")
    w("")
    status = "方案待确认" if review.get("ok") else "方案待确认（审稿未完全通过，见文末审稿意见）"
    w(f"> 状态：{status}（Step 1–4 已完成，Step 5 代码生成需确认后启动）")
    w(f"> 推导引擎：Agent Blueprint · 模型：{plan.runner}")
    if plan.runner == "mock":
        w("> 离线演示：方案与审稿为占位结果，仅用于预览流程，不能作为真实产品决策依据。")
    w("")
    w("## 产品定位（一句话）")
    w("")
    w(f"**{plan.title}**：{ex.get('one_liner', '')}")
    w("")

    # 待确认清单放前面，小白最先要看的就是这个
    unknowns = list(ex.get("unknowns", [])) + list(design.get("open_questions", []) or [])
    pending_components = [d for d in plan.components if d["decision"] == "待确认"]
    w("## ⚠️ 待确认清单（答不上就是风险点）")
    w("")
    if not unknowns and not pending_components:
        w("输入信息完整，无待确认项。")
    n = 0
    for q in unknowns:
        n += 1
        w(f"{n}. {q}")
    for d in pending_components:
        n += 1
        w(f"{n}. 【组件 {d['id']} {d['name']}】{describe_feature(d.get('feature', ''))}")
    w("")

    w("## Step 1 · 需求拆解（提取硬事实）")
    w("")
    w("| 维度 | 结论 | 状态 | 出处 |")
    w("|---|---|---|---|")
    for key, label in _FACT_LABEL.items():
        f = facts.get(key, {})
        w(f"| {label} | {_cell(f.get('value')) or '（空）'} | {f.get('status', '待确认')} | {_cell(f.get('source'))} |")
    w("")

    w("## Step 2 · 领域建模（映射 Harness 五要素）")
    w("")
    w("| 要素 | 内容 |")
    w("|---|---|")
    for key, label in _ELEMENT_LABEL.items():
        items = plan.elements.get(key, [])
        w(f"| **{label}** | {'；'.join(_cell(i) for i in items) or '（待补充）'} |")
    w("")

    w("## Step 3 · 组件选型（宁可少选）")
    w("")
    w("| 组件 | 选否 | 理由 | 参考 |")
    w("|---|---|---|---|")
    mark = {"必选": "✅ 必选", "二期": "⏸ 二期", "待确认": "❓ 待确认", "放弃": "❌ 放弃"}
    for d in plan.components:
        comp = COMPONENT_BY_ID[d["id"]]
        w(f"| {d['id']} {d['name']} | {mark[d['decision']]} | {_cell(d['reason'])} | {comp.readme} |")
    w("")
    w("特征判定依据：")
    w("")
    for fid, fv in features.items():
        w(f"- `{fid}` = {fv.get('value')}：{_cell(fv.get('evidence'))}")
    w("")

    w("## Step 4 · 架构设计")
    w("")
    w("### 分层架构图（7 层 + 数据流）")
    w("")
    w(render_mermaid(plan.title, plan.components, design.get("tool_list", []), facts,
                     design.get("tech_stack_and_deployment", "")))
    w("")
    w("| 层 | 名称 | 回答的问题 | 落地锚点 |")
    w("|---|---|---|---|")
    for num, name, q, anchor in LAYERS:
        w(f"| {num} | {name} | {q} | {anchor} |")
    w("")

    w("### 工具清单")
    w("")
    w("| 工具 | 输入 | 输出 | 副作用 | 权限 | 归属层 |")
    w("|---|---|---|---|---|---|")
    for t in design.get("tool_list", []):
        w(f"| `{t['name']}` | {_cell(t['input'])} | {_cell(t['output'])} | {_cell(t['side_effect'])} | {t['permission']} | {t['layer']} |")
    w("")

    w("### 系统提示词草案")
    w("")
    w("```")
    w(design.get("system_prompt", "").strip())
    w("```")
    w("")

    w("### 上下文与记忆策略")
    w("")
    w(design.get("context_memory_strategy", "").strip())
    w("")

    w("### 安全边界与降级策略")
    w("")
    for line in design.get("security_and_degradation", []):
        w(f"- {line}")
    w("")

    obs = design.get("observability", {})
    w("### 可观测性")
    w("")
    w("- 日志：" + "；".join(obs.get("logs", [])))
    w("- 指标：" + "；".join(obs.get("metrics", [])))
    w("- 轨迹：" + _cell(obs.get("trajectory")))
    w("")

    w("### 技术栈与部署形态")
    w("")
    w(design.get("tech_stack_and_deployment", "").strip())
    w("")

    w("## 验收标准对照（可落地 vs demo）")
    w("")
    w("| 标准 | 要求 | 本方案的对应设计 |")
    w("|---|---|---|")
    mapping = {
        "runnable": design.get("tech_stack_and_deployment", ""),
        "fault_tolerant": "；".join(design.get("security_and_degradation", [])[:3]),
        "observable": "；".join(obs.get("logs", [])[:2] + obs.get("metrics", [])[:2]),
        "testable": "Step 5 骨架层需附核心循环与权限边界的单测",
        "deployable": design.get("tech_stack_and_deployment", ""),
        "measurable": "；".join(obs.get("metrics", [])),
    }
    for key, (name, desc) in ACCEPTANCE.items():
        w(f"| {name} | {desc} | {_cell(mapping.get(key)) or '（待补充）'} |")
    w("")

    w("## 独立审稿意见")
    w("")
    verdict = "✅ 通过" if review.get("ok") else "❌ 未通过"
    score = review.get("score")
    w(f"- 结论：{verdict}" + (f"（{score} / 100）" if score is not None else "") + f"，设计稿共 {plan.design_attempts} 版")
    w(f"- 总评：{_cell(review.get('summary'))}")
    for i in review.get("issues", []):
        w(f"- [{i.get('severity', '')}] {i.get('section', '')}：{_cell(i.get('problem'))}")
    w("")

    if plan.budget:
        b = plan.budget
        w("## 本次推导消耗")
        w("")
        w(f"- 模型调用 {b.get('calls', 0)} 次，输入 {b.get('input_tokens', 0)} tokens，输出 {b.get('output_tokens', 0)} tokens")
        w("")

    w("## 下一步")
    w("")
    w("回答上面的待确认清单，据此修订方案后，再进入 Step 5 代码生成（骨架 → 硬化 → 产品化）。")
    w("")
    return "\n".join(out)
