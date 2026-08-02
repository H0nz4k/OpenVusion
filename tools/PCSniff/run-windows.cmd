@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtualenv...
  py -3 -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -U pip
  pip install -e "..\ElaTool"
  pip install -e ".[dev]"
) else (
  call .venv\Scripts\activate.bat
)

py -m twn4_capture_probe --auto-port %*
endlocal
