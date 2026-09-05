# Agent Blueprint —— Agent 产品需求引擎

[![Test](https://github.com/hubooooooo/agent-blueprint/actions/workflows/test.yml/badge.svg)](https://github.com/hubooooooo/agent-blueprint/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 给它一个 PRD、一个需求点子、或一个可落地的 Agent 方向，它推导出架构方案、组件选型与代码骨架，直到一个能在真实环境运行的产品。

**Python 3.10+ · macOS / Linux · MIT**

推导入口：**[BLUEPRINT.md](./BLUEPRINT.md)**。仓库同时提供 `s01`–`s17` 共 17 个可运行组件参考实现，覆盖 Agent Harness 从行动、约束、认知到编排的完整机制。

---

## 这是什么

Agent Blueprint 是一套「从 PRD 到 Agent 产品」的推导引擎：

- **方法论**：[BLUEPRINT.md](./BLUEPRINT.md) 定义五步 SOP、架构决策映射表、生产级组件库与验收标准。
- **组件参考实现**：`s01`–`s17` 每个组件一个独立 `code.py`，展示一个 Harness 机制如何落地。
- **生产骨架**：[scaffold/](./scaffold/) 提供可扩展的生产级 Agent 项目模板。
- **领域技能**：[skills/](./skills/) 内置 agent-builder、code-review、mcp-builder 等技能。

🌱 纯小白、只有一个想法还没 PRD？先看 **[《纯小白入门指南》](./docs/beginner-guide.md)**。

---

## 核心模型

```text
Agent = 模型（智能，已训练好） + Harness（载具，你构建的代码）
```

```text
Harness = 工具 + 知识 + 观察 + 行动接口 + 权限
```

模型做决策，Harness 执行。你构建的是 Harness，不是智能。

---

## 从 PRD 到产品：五步推导

```text
PRD / 点子 / 方向
      │
      ▼
① 需求拆解   从 PRD 提取硬事实（目标/用户/闭环/边界/约束），缺失标注「待确认」
      │
      ▼
② 领域建模   把事实映射到 Harness 五要素（工具/知识/观察/行动/权限）
      │
      ▼
③ 组件选型   查「组件选型速查表」，只选需要的组件
      │
      ▼
④ 架构设计   产出方案：分层架构图（7 层）/工具清单/系统提示词/安全边界/部署形态
      │
      ▼ （确认后再生成代码）
⑤ 代码生成   骨架 → 硬化 → 产品化
```

**原则：先方案，确认后再生成代码。**

---

## 组件选型速查表

| 场景 / PRD 特征 | 组件 | 一句话 | 参考 |
|---|---|---|---|
| 一切基础：循环 + 工具 | Agent Loop | 最小可运行闭环 | [s01](./s01_agent_loop/) |
| 需要调用外部系统/API/数据源 | 工具系统 | 循环不变，工具可增 | [s02](./s02_tool_use/) |
| 涉及破坏性/敏感操作 | 权限系统 | 先划边界，再给自由 | [s03](./s03_permission/) |
| 需要审计、拦截、埋点 | 钩子系统 | 挂循环上，不写循环里 | [s04](./s04_hooks/) |
| 多步骤、需跟踪进度 | 任务规划 | 先计划后执行 | [s05](./s05_todo_write/) |
| 上下文会爆、任务可并行 | 子 Agent | 全新消息列表，隔离噪声 | [s06](./s06_subagent/) |
| 领域知识库庞大 | 技能加载 | 用到时再加载 | [s07](./s07_skill_loading/) |
| 长会话、日志量大 | 上下文压缩 | 长上下文腾空间 | [s08](./s08_context_compact/) |
| 需跨会话记住偏好/决策 | 记忆系统 | 记住该记的，忘掉该忘的 | [s09](./s09_memory/) |
| 目标需持久化、断点续跑 | 任务系统 | 大目标拆小任务，持久化 | [s10](./s10_task_system/) |
| 有慢操作需不阻塞 | 后台任务 | 慢操作丢后台 | [s11](./s11_background_tasks/) |
| 需定时自治触发 | 定时调度 | 到点自动触发 | [s12](./s12_cron_scheduler/) |
| 多任务并行、需隔离工作区 | Agent 团队 | 队友分工协作 | [s13](./s13_agent_teams/) |
| 需接入外部工具生态 | MCP 插件 | 外部工具接入同一工具池 | [s14](./s14_mcp_plugin/) |
| 上述机制需协同 | 集成 Harness | 多机制归一循环 | [s15](./s15_integrated_harness/) |
| 编排形态固定 | 工作流运行时 | 编排形状固定就写进代码 | [s16](./s16_workflow_runtime/) |
| 需自动判断「何时算完成」 | 目标闭环 | 目标决定循环何时停止 | [s17](./s17_goal_loop/) |

完整说明（含生产级要点）见 **[BLUEPRINT.md](./BLUEPRINT.md)**。

---

## 核心循环

```python
def agent_loop(messages):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, tools=TOOLS,
        )
        messages.append({"role": "assistant",
                         "content": response.content})

        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        if not tool_calls:
            return

        results = []
        for block in tool_calls:
            output = TOOL_HANDLERS[block.name](**block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})
```

循环属于 Agent，机制属于 Harness。这个循环是常量；工具、知识、权限随领域而变。

---

## 快速开始

> 要求 Python 3.10+，仅支持 macOS / Linux（部分组件依赖 `fcntl` 等 Unix 特性）。

### 1. 安装环境

```sh
./setup.sh
```

或手动安装：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

### 2. 配置密钥

打开 `.env`，填入 `ANTHROPIC_API_KEY` 和 `MODEL_ID`。也支持 Anthropic-compatible 的 MiniMax、GLM、Kimi、DeepSeek 等 provider。

### 3. 运行

```sh
# 最小 agent loop
.venv/bin/python s01_agent_loop/code.py

# 集成 harness 参考
.venv/bin/python s15_integrated_harness/code.py

# 目标闭环
.venv/bin/python s17_goal_loop/code.py

# 无 API Key 也能跑的离线 workflow demo
.venv/bin/python s16_workflow_runtime/code.py demo
```

### 4. 跑测试

```sh
.venv/bin/python -m pytest -q
```

**从 PRD 推导产品**：把 [BLUEPRINT.md](./BLUEPRINT.md)（或相关章节）连同你的 PRD 一起交给 AI，要求按五步 SOP 推导，并遵守「先方案后代码」。

---

## 项目结构

```text
agent-blueprint/
  BLUEPRINT.md                     # 核心蓝图 + PRD 推导 SOP
  docs/                            # 入门指南、需求文档、示例 PRD
  scaffold/                        # 生产级项目模板
  skills/                          # 领域技能（agent-builder 等）
  s01_agent_loop/                  # 组件参考实现，每个文件夹包含：
    README.md                      #   组件说明
    code.py                        #   独立可运行代码
    images/                        #   架构图
  s02_tool_use/
  ...
  s17_goal_loop/
  tests/                           # 测试套件
```

---

## 文档

- [BLUEPRINT.md](./BLUEPRINT.md)：核心方法论与生产级组件库。
- [docs/beginner-guide.md](./docs/beginner-guide.md)：纯小白入门指南。
- [docs/requirements.md](./docs/requirements.md)：需求说明。
- [docs/prd-toy-theater.md](./docs/prd-toy-theater.md)：示例 PRD。

---

## 作者与许可

- 作者：Hubo
- 许可：[MIT](./LICENSE)，Copyright (c) 2024 Hubo
