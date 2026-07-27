@echo off
chcp 65001 >nul
title 关闭员工信息管理系统

REM ============================================================
REM  关闭脚本：只结束占用服务端口（默认 5001）的进程，
REM  不会影响电脑上其他正在运行的 Python 程序。
REM ============================================================

if "%GZD_PORT%"=="" set "GZD_PORT=5001"

echo 正在关闭项目（端口 %GZD_PORT%）...

set "FOUND="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%GZD_PORT% " ^| findstr "LISTENING"') do (
    set "FOUND=1"
    taskkill /F /PID %%a >nul 2>nul
)

echo.
if defined FOUND (
    echo 已关闭员工信息管理系统。
) else (
    echo 未发现正在运行的服务（端口 %GZD_PORT% 未被占用）。
)
pause
