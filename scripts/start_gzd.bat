@echo off
chcp 65001 >nul
setlocal
rem 跳转到项目根目录（本脚本位于 scripts\ 下）
cd /d "%~dp0.."

set "PORT=5001"
if not "%GZD_PORT%"=="" set "PORT=%GZD_PORT%"

rem 服务已在运行：直接打开页面，不再重复启动
netstat -ano | findstr /c:":%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] 服务已在运行，正在打开页面...
    start "" "http://127.0.0.1:%PORT%"
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

echo 正在启动员工信息管理系统，请稍候...
set "GZD_DEBUG=0"
start "gzd-server" /min "D:\env\msys2\mingw64\bin\python.exe" "app.py"

rem 最多等待 15 秒，端口就绪后才打开页面（Python 加载依赖需要几秒）
set /a TRIES=15
:wait_loop
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /c:":%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 goto started
set /a TRIES-=1
if %TRIES% gtr 0 goto wait_loop

echo [错误] 服务启动失败，请查看 logs 目录下的日志排查原因
pause
exit /b 1

:started
echo 启动成功，正在打开页面...
start "" "http://127.0.0.1:%PORT%"
exit /b 0
