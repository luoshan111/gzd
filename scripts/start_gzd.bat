@echo off
setlocal
rem Jump to project root (this script lives in scripts\)
cd /d "%~dp0.."

set "PORT=5001"
if not "%GZD_PORT%"=="" set "PORT=%GZD_PORT%"

rem Start the server only if nothing is listening on the port yet
netstat -ano | findstr /c:":%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if errorlevel 1 (
    set "GZD_DEBUG=0"
    start "gzd-server" /min "D:\env\msys2\mingw64\bin\python.exe" "app.py"
    timeout /t 3 /nobreak >nul
)

rem Open the project page in the default browser
start "" "http://127.0.0.1:%PORT%"
endlocal
