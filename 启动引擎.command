#!/bin/bash
# Agent Blueprint 启动器（Mac）
# 双击本文件即可：自动检测 / 安装 Python → 初始化环境 → 进入一问一答引导。
set -uo pipefail
cd "$(dirname "$0")"

PY_VER="3.12.7"
PY_PKG="python-${PY_VER}-macos11.pkg"
PY_URL="https://www.python.org/ftp/python/${PY_VER}/${PY_PKG}"

find_python() {
  local cand maj min
  for cand in \
      "$HOME/.local/bin/python3.12" "$HOME/.local/bin/python3.11" "$HOME/.local/bin/python3.10" \
      "/opt/homebrew/bin/python3.12" "/opt/homebrew/bin/python3.11" "/opt/homebrew/bin/python3" \
      "/usr/local/bin/python3.12" "/usr/local/bin/python3.11" "/usr/local/bin/python3" \
      "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
      "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
      "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3" \
      python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      maj=$("$cand" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
      min=$("$cand" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
      if [ "$maj" -gt 3 ] || { [ "$maj" -eq 3 ] && [ "$min" -ge 10 ]; }; then
        echo "$cand"
        return 0
      fi
    fi
  done
  return 1
}

echo "==> 检查 Python 环境 ..."
PY="$(find_python)"
if [ -z "$PY" ]; then
  echo "检测到这台 Mac 还没安装 Python 3.10+，正在帮你下载安装包（约 40MB）…"
  PKG="/tmp/agent-blueprint-python.pkg"
  if curl -L --fail --silent --show-error -o "$PKG" "$PY_URL"; then
    open "$PKG"
    echo ""
    echo "已打开 Python 安装器。请在弹出窗口里一路点「继续 / 同意」完成安装。"
  else
    echo "自动下载失败。请手动到 https://www.python.org/downloads/ 下载并安装 Python 3.12。"
  fi
  echo ""
  echo "装好之后，重新双击本文件即可开始使用。"
  read -r -p "按回车关闭窗口 ..."
  exit 1
fi
echo "✅ 使用：$("$PY" --version)"

if [ ! -d ".venv" ]; then
  echo "==> 首次初始化（创建环境，约 1 分钟）..."
  "$PY" -m venv .venv
fi

echo "==> 安装依赖（已装好的会跳过）..."
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -q -r requirements.txt

echo "==> 进入引导 ..."
exec .venv/bin/python tools/wizard.py
