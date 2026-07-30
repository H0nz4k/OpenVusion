@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Nejdrive spust install_windows.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m elatec_uid_tool interactive
echo.
pause
