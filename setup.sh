#!/usr/bin/env bash
# 一键初始化开发环境（macOS / Linux）
# 用法：在项目根目录执行 ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 检查 Python ..."
PY=""
# macOS 系统自带 python3 常是 3.9，这里优先找 3.12 / 3.11 / 3.10
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" &>/dev/null; then
    maj=$("$cand" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
    min=$("$cand" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
    if [ "$maj" -gt 3 ] || { [ "$maj" -eq 3 ] && [ "$min" -ge 10 ]; }; then
      PY="$cand"
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "❌ 未找到 Python 3.10+。请先安装："
  echo "   - 官网安装包：https://www.python.org/downloads/ （macOS 选 macOS installer）"
  echo "   - 或 Homebrew：brew install python@3.12"
  exit 1
fi
echo "✅ 使用 $(command -v "$PY")（$("$PY" --version)）"

echo "==> 创建虚拟环境 .venv ..."
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
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
echo "   2. 阅读 使用引导.md，或运行：.venv/bin/python -m blueprint --help"
