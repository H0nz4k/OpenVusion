@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set "PYTHON=.venv\Scripts\python.exe"

where py >nul 2>nul
if errorlevel 1 (
    echo CHYBA: Python launcher "py" nebyl nalezen.
    echo Nainstaluj Python 3.10 nebo novejsi a zapni volbu Add Python to PATH.
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo Vytvarim virtualni prostredi...
    py -m venv .venv
    if errorlevel 1 goto :install_error
)

echo Kontroluji instalaci ELATEC UID Tool...
"%PYTHON%" -m pip install --disable-pip-version-check -q -e .
if errorlevel 1 goto :install_error

for /f "delims=" %%V in ('"%PYTHON%" -m elatec_uid_tool --version') do set "TOOL_VERSION=%%V"

:menu
cls
echo ========================================================================
echo                     %TOOL_VERSION%
echo ========================================================================
echo.
echo   1. Tests - otestovat medium a vypsat jeho typ
echo   2. Interactive mode - hledani UID a pravidla pro AppBlaster
echo   3. Update reader - priprava PRS a vlastniho firmware
echo   0. Konec
echo.
set /p "CHOICE=Vyber 0-3: "

if "%CHOICE%"=="1" goto :test_medium
if "%CHOICE%"=="2" goto :interactive
if "%CHOICE%"=="3" goto :update_reader
if "%CHOICE%"=="0" goto :end

echo.
echo Neplatna volba.
pause
goto :menu

:test_medium
cls
"%PYTHON%" -m elatec_uid_tool test-medium
call :pause_and_menu
goto :menu

:interactive
cls
"%PYTHON%" -m elatec_uid_tool interactive
call :pause_and_menu
goto :menu

:update_reader
cls
"%PYTHON%" -m elatec_uid_tool update-reader --devpack "%~dp0files520"
call :pause_and_menu
goto :menu

:pause_and_menu
echo.
pause
exit /b 0

:install_error
echo.
echo Instalace nebo aktualizace projektu selhala.
pause
exit /b 1

:end
endlocal
exit /b 0
