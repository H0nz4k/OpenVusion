#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
sudo bash "${DIR}/install.sh" --no-start "$@"
sudo systemctl restart hwsniff.service
echo "Updated and restarted hwsniff."
