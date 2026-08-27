@echo off
title 员工信息管理系统

REM ============================================================
REM  员工信息管理系统 - 启动脚本
REM  以本脚本所在目录为项目目录，无论文件夹移动到哪里，
REM  直接双击本文件即可启动，无需修改任何路径。
REM ============================================================

REM 切换到本脚本所在目录（%~dp0 = 当前 bat 文件所在的目录）
cd /d "%~dp0.."

REM 查找可用的 Python：优先 PATH 中的 python，其次 Windows py 启动器
set "PYTHON="
where python >nul 2>nul && set "PYTHON=python"
if not defined PYTHON (
    where py >nul 2>nul && set "PYTHON=py -3"
)
if not defined PYTHON (
    echo [错误] 未找到 Python，请先安装 Python 3 并勾选 "Add Python to PATH"
    pause
    exit /b 1
)

REM 验证 Python 能正常运行（排除 Windows 应用商店占位程序）
%PYTHON% --version >nul 2>nul
if errorlevel 1 (
    echo [错误] 检测到的 Python 无法运行（可能是应用商店占位程序），请安装正式的 Python 3
    pause
    exit /b 1
)

REM 检查依赖，首次运行或依赖缺失时自动安装
%PYTHON% -c "import flask, pandas, openpyxl, pypinyin, werkzeug" >nul 2>nul
if errorlevel 1 (
    echo 检测到缺少依赖，正在自动安装...
    %PYTHON% -m pip install flask pandas openpyxl pypinyin Werkzeug
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

echo 正在启动员工信息管理系统...
echo.
echo 启动成功后，请访问: http://127.0.0.1:5001
echo 局域网其他设备请访问: http://本机IP地址:5001
echo.
echo 按 Ctrl + C 可以停止服务
echo ================================
echo.

REM 以单进程模式运行（关闭调试重载器），保证"关闭项目.bat"能可靠结束服务；
REM 开发调试时可去掉下面这行，或手动执行 python app.py
set "GZD_DEBUG=0"

REM 启动应用（端口可用环境变量 GZD_PORT 覆盖，默认 5001）
%PYTHON% app.py

pause
