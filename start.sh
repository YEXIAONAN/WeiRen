#!/usr/bin/env bash
set -e

# 伪人 — 一键启动脚本 (Linux/macOS)

cd "$(dirname "$0")"

# Python 检测
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "错误：未找到 Python 3，请先安装 Python 3.11+"
    exit 1
fi

# 虚拟环境
if [ ! -d .venv ]; then
    echo ">>> 创建虚拟环境..."
    "$PYTHON" -m venv .venv
fi

# 兼容 macOS 旧版 bash 不支持 source
if [ -n "$BASH_VERSION" ] && [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    . .venv/bin/activate
else
    source .venv/bin/activate
fi

# 依赖
echo ">>> 安装依赖..."
pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt

# 初始化数据库
echo ">>> 初始化数据库..."
python scripts/init_db.py

# 启动
echo ""
echo "======================================"
echo "  伪人 已启动"
echo "  访问地址: http://127.0.0.1:8000"
echo "======================================"
echo ""

uvicorn weiren.main:app --reload --host 127.0.0.1 --port 8000
