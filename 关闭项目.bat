@echo off
chcp 65001 >nul
echo 正在关闭项目...
taskkill //F //IM python.exe
echo.
echo 已执行关闭命令。
pause
