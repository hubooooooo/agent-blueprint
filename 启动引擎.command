#!/bin/bash
# Agent 工坊 启动器（Mac）
# 双击本文件即可：自动检测 / 安装 Python → 初始化环境 → 进入一问一答引导。
# 不习惯终端的话，双击「启动界面.command」用浏览器界面。
set -uo pipefail
cd "$(dirname "$0")"
source tools/mac_env.sh
prepare_env || exit 1

echo "==> 进入引导 ..."
exec .venv/bin/python tools/wizard.py
