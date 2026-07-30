@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Nejdrive spust install_windows.bat
    pause
    exit /b 1
)

set /p DEVPACK=Zadej cestu ke koreni TWN4 Developer Packu: 
".venv\Scripts\python.exe" -m elatec_uid_tool prepare-reader --devpack "%DEVPACK%"
echo.
pause
