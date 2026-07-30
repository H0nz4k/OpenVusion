@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Nejdrive spust install_windows.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :error

".venv\Scripts\python.exe" scripts\check_version.py
if errorlevel 1 goto :error

echo.
echo Vsechny kontroly prosly.
pause
exit /b 0

:error
echo.
echo Kontroly selhaly.
pause
exit /b 1
