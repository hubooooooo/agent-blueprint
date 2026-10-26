#!/bin/bash
# Agent Blueprint 网页界面（Mac）
# 双击本文件即可：自动检测 / 安装 Python → 初始化环境 → 在浏览器里打开界面。
# 用的时候别关这个窗口；用完直接关掉即可。
set -uo pipefail
cd "$(dirname "$0")"
source tools/mac_env.sh
prepare_env || exit 1

echo "==> 打开界面 ..."
exec .venv/bin/python -m blueprint ui
