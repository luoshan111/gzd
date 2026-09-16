@echo off
setlocal
cd /d "%~dp0.."

set "PORT=5001"
if not "%GZD_PORT%"=="" set "PORT=%GZD_PORT%"

netstat -ano | findstr /c:":%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    start "" "http://127.0.0.1:%PORT%"
    exit /b 0
)

echo Starting Employee Information System...
set "GZD_DEBUG=0"

set "PYTHON=%~dp0..\.runtime\python\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON="
    where python >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    echo ERROR: Python runtime was not found.
    pause
    exit /b 1
)

%PYTHON% -c "import flask, openpyxl, pypinyin, sqlite3" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python runtime is incomplete.
    pause
    exit /b 1
)

start "gzd-server" /min "%PYTHON%" "app.py"

set /a TRIES=15
:wait_loop
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /c:":%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 goto started
set /a TRIES-=1
if %TRIES% gtr 0 goto wait_loop

echo ERROR: Service failed to start. Check the logs folder.
pause
exit /b 1

:started
start "" "http://127.0.0.1:%PORT%"
exit /b 0
