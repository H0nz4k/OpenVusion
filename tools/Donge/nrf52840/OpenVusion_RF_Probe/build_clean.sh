#!/usr/bin/env bash
set -euo pipefail
export CCACHE_DISABLE=1
export CMAKE_BUILD_PARALLEL_LEVEL=1
rm -rf build
west build -p always -b nrf52840dongle/nrf52840 -d build .
python3 verify_build.py build
echo
echo "BUILD + VERIFY PASS"
echo "Expected runtime: exactly ONE CDC ACM serial port."
