@echo off
chcp 65001 >nul
cd /d "E:\code\c\gongzidan"
echo 正在启动员工信息管理系统...
echo.
echo 启动成功后，请访问: http://127.0.0.1:5001
echo.
echo 局域网其他设备请访问: http://你的IP地址:5001
echo.
echo 按 Ctrl + C 可以停止服务
echo ================================
echo.
E:\anaconda1\python.exe -c "from app import app; app.run(port=5001, debug=True, host='0.0.0.0')"
pause
