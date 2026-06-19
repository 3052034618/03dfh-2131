@echo off
chcp 65001 >nul 2>&1
title 硬核推理车队招募助手
cd /d "%~dp0"
echo.
echo 正在启动 Hardcore Car Manager ...
echo.
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)"
if %errorlevel% neq 0 (
    echo [错误] Python 版本过低，请升级到 3.8 或更高
    pause
    exit /b 1
)
python hardcore_car.py
if %errorlevel% neq 0 (
    echo.
    echo 程序异常退出，错误代码: %errorlevel%
    pause
)
