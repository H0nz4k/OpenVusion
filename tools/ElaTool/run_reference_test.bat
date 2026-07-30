@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Nejdrive spust install_windows.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m elatec_uid_tool analyze --raw 3D00C000D4 --bits 40 --expected 12583124 --expected-format decimal
echo.
pause
