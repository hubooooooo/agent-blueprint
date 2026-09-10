# Agent Blueprint —— 本地 Agent 需求引擎

[![Test](https://github.com/hubooooooo/agent-blueprint/actions/workflows/test.yml/badge.svg)](https://github.com/hubooooooo/agent-blueprint/actions/workflows/test.yml)

给 AI 一个点子或项目路径，它按本地引擎的规则生成架构方案或差距报告。结果保存为文件。

## 学生上手

先看 **[使用引导.md](使用引导.md)**。把下面的话交给能读取本地文件的 AI，替换路径和任务：

```text
引擎目录：/你的路径/agent-blueprint
先读这里的《使用引导.md》。
请检查这个项目：/你的路径/目标项目。
生成差距报告，告诉我先补什么、结果在哪里，先不要修改项目代码。
```

只有点子时，改成“我的点子是……，请生成方案”。没有单独配置模型接口时，当前 AI 可以按手册分析，并注明未运行程序模型管线。

没把握能拿到什么？先看 [输出示例](docs/examples/README.md)（一份正向方案 + 一份反向差距报告）。

## Mac 双击版（给纯小白，无需命令行）

Mac 同学直接双击 **`启动引擎.command`**，会弹出终端窗口，一问一答带你：

1. 选模型服务商（推荐 DeepSeek）→ 粘贴 API Key → 自动测试连接；
2. 选「生成方案」或「检查差距」→ 粘贴想法或项目路径；
3. 自动推导，结果存在 `out/` 并提示打开。

首次双击会自动检测 Python，没装会帮你下载安装。没有 API Key 也可以先用「离线演示」体验流程。

## 程序运行

以下操作可交给 AI 或维护者。要求 Python 3.10+，macOS / Linux。

```sh
bash setup.sh

# 不调用外部模型，检查流程是否可用
.venv/bin/python -m blueprint plan "做一个每天提醒喝水的助手" --mock
.venv/bin/python -m blueprint audit ./scaffold --mock
```

真实程序推导需要维护者在 `.env` 配置 `ANTHROPIC_API_KEY`、`MODEL_ID`，然后省略 `--mock`。每次任务指定独立的输出目录：

```sh
.venv/bin/python -m blueprint plan docs/prd-toy-theater.md -o out/my-plan
.venv/bin/python -m blueprint audit /目标项目路径 -o out/my-audit
# 失败后复用原目录续跑
.venv/bin/python -m blueprint plan docs/prd-toy-theater.md -o out/my-plan --resume
```

`out/` 保存 `方案.md`、`差距报告.md`、反推 PRD 和 JSON 结果。演示结果只验证流程；静态审计不能代替真实运行验收。方案确认后的产品代码开发属于后续任务。

## 文件导航

| 文件或目录 | 用途 |
|---|---|
| [使用引导.md](使用引导.md) | 用户给 AI 的任务模板及执行步骤 |
| [BLUEPRINT.md](BLUEPRINT.md) | 五步推导、五要素、七层架构与组件选型表 |
| [blueprint/](blueprint/) | 正反向引擎、规则、扫描、审稿、续跑 |
| [小白入门指南](docs/beginner-guide.md) | 把模糊点子说清楚 |
| [玩具剧场 PRD](docs/prd-toy-theater.md) | 完整需求示例（正向方案产出） |
| [输出示例](docs/examples/README.md) | 正向方案与反向差距报告长什么样 |
| `s01`–`s17` | 17 个组件的说明、代码和图示；目录索引见蓝图 |
| [scaffold/](scaffold/) | 后续开发使用的项目模板 |
| [skills/](skills/) | 构建 Agent、代码检查等技能示例 |
| [evals/](evals/) / [tests/](tests/) | 规则题库、管线与组件回归 |
| [维护手册](docs/维护手册.md) | 改规则、换模型、验证和学生分发 |

## 验证与分发

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
.venv/bin/python -m blueprint eval

# 生成学生用的纯文件压缩包
python3 tools/package_student.py
```

把 `dist/agent-blueprint-student.zip` 发给学生即可。压缩包保留引擎、手册、全部组件参考和测试，排除本机密钥、虚拟环境、Git 历史、运行结果及缓存。不要直接压缩整个开发目录。

作者：Hubo · [MIT 许可证](LICENSE) · [教程视频](https://www.bilibili.com/video/BV17RtD61ETm/)
