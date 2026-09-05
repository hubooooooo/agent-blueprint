#!/usr/bin/env bash
# 一键初始化开发环境（macOS / Linux）
# 用法：在项目根目录执行 ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 检查 Python ..."
if ! command -v python3 &>/dev/null; then
  echo "❌ 未找到 python3。请先安装 Python 3.10+："
  echo "   - 官网安装包：https://www.python.org/downloads/ （macOS 选 macOS installer）"
  echo "   - 或 Homebrew：brew install python"
  exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "❌ Python 版本过低（当前 ${PY_MAJOR}.${PY_MINOR}），需要 3.10+"
  exit 1
fi
echo "✅ Python ${PY_MAJOR}.${PY_MINOR}"

echo "==> 创建虚拟环境 .venv ..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "    已创建 .venv"
else
  echo "    .venv 已存在，跳过"
fi

echo "==> 安装依赖 ..."
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt

echo "==> 生成 .env ..."
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "    已生成 .env（请打开填入你的 ANTHROPIC_API_KEY）"
else
  echo "    .env 已存在，跳过"
fi

echo ""
echo "🎉 环境就绪！下一步："
echo "   1. 打开 .env 填入 ANTHROPIC_API_KEY（和 MODEL_ID）"
echo "   2. 运行：.venv/bin/python s01_agent_loop/code.py"
