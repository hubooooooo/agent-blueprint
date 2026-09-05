# 项目长期需求记录

> 此文件记录需要**长期遵守**的需求与约束。每次改动项目前，先看这里。
> 状态标记：⏳ 待执行 / ✅ 已落实 / 🕒 持续有效

---

## 需求 1：打包分发给学生（🕒 持续有效）

- **需求**：项目优化完成后，打包成压缩包（zip），分发给其他学生使用（多数为 macOS）。
- **含义**：
  1. 项目必须**自包含**：学生解压即用，不依赖本机绝对路径、不依赖对话上下文。
  2. 打包时**排除**：`.venv/`、`.git/`、`__pycache__/`、`.pytest_cache/`、`.DS_Store`、`.env`（含密钥）、`.transcripts/`、`.runtime/` 等运行产物。
  3. 打包时**包含**：`setup.sh`、`.vscode/`（VS Code 引导配置）、`.env.example`（模板，无密钥）、`requirements.txt`（已锁版本）。
  4. 必须附带**学生上手说明**（见 README「学生上手」一节）。
- **状态**：⏳ 待执行（等优化完成后打包）。

---

## 决策 1：学生环境初始化方案（✅ 已落实）

- **问题**：每台 Mac 环境不同，`.venv` 不能随包分发（含绝对路径、平台二进制）。
- **方案**（不依赖 Docker）：
  1. `setup.sh` 一键脚本：检查 Python 版本 → 建 `.venv` → 装依赖 → 生成 `.env`。
  2. `.vscode/`：`extensions.json`（推荐 Python 扩展）、`settings.json`（指向 `.venv` 解释器）、`tasks.json`（「一键初始化环境」任务）。
  3. `requirements.txt` 锁定到已测试版本，保证各机器安装结果一致。
- **为什么不用 Dev Container**：需要学生装 Docker Desktop（数 GB、占内存），对只有 3 个纯 Python 依赖的项目过重。
