$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtualenv..."
    py -3 -m venv .venv
    & .\.venv\Scripts\Activate.ps1
    pip install -U pip
    pip install -e "..\ElaTool"
    pip install -e ".[dev]"
} else {
    & .\.venv\Scripts\Activate.ps1
}

py -m twn4_capture_probe --auto-port @args
