@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo CHYBA: Python launcher "py" nebyl nalezen.
    echo Nainstaluj Python 3.10 nebo novejsi a zapni volbu Add Python to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Vytvarim virtualni prostredi...
    py -m venv .venv
    if errorlevel 1 goto :error
)

echo Aktualizuji pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo Instaluji projekt a pyserial...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :error

echo.
echo Instalace dokoncena.
echo Pro hlavni menu spust elaUIDtool.bat
pause
exit /b 0

:error
echo.
echo Instalace selhala.
pause
exit /b 1
