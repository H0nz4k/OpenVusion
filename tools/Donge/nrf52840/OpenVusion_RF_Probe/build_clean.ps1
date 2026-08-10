$ErrorActionPreference = "Stop"

Write-Host "OpenVusion RF Probe v0.6.1 - deterministic clean build"
Write-Host "Target: nrf52840dongle/nrf52840"

$env:CCACHE_DISABLE = "1"
$env:CMAKE_BUILD_PARALLEL_LEVEL = "1"

if (Test-Path "build") {
    Write-Host "Removing old build directory..."
    Remove-Item -Recurse -Force "build"
}

west build -p always -b nrf52840dongle/nrf52840 -d build .

if ($LASTEXITCODE -ne 0) {
    throw "west build failed with exit code $LASTEXITCODE"
}

python verify_build.py build

if ($LASTEXITCODE -ne 0) {
    throw "Build verification failed. DO NOT FLASH."
}

Write-Host ""
Write-Host "BUILD + VERIFY PASS"
Write-Host "Expected runtime: exactly ONE CDC ACM serial port."
