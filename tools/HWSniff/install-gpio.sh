#!/usr/bin/env bash
# Compatibility wrapper → tools/HWSniff/deploy/install-on-pi.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/deploy/install-on-pi.sh" "$@"
