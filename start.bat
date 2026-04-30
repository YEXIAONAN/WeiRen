@echo off
cd /d "%~dp0"

REM 伪人 — 一键启动脚本 (Windows)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误：未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

if not exist .venv (
    echo ^>^>^> 创建虚拟环境...
    python -m venv .venv
)

echo ^>^>^> 激活虚拟环境...
call .venv\Scripts\activate.bat

echo ^>^>^> 安装依赖...
pip install -q -r requirements.txt 2>nul || pip install -r requirements.txt

echo ^>^>^> 初始化数据库...
python scripts\init_db.py

echo.
echo ======================================
echo  伪人 已启动
echo  访问地址: http://127.0.0.1:8000
echo ======================================
echo.

uvicorn weiren.main:app --reload --host 127.0.0.1 --port 8000

pause
