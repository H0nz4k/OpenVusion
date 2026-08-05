#!/usr/bin/env bash
# Runs ON the Pi after code was uploaded to /tmp/hwsniff-quick/
# Syncs into /opt/Sniff and optionally restarts the service.
set -euo pipefail

SRC="${1:-/tmp/hwsniff-quick}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/Sniff}"
RESTART="${RESTART:-1}"
SERVICE_USER="${SERVICE_USER:-hwsniff}"

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root: sudo bash remote-quick-update.sh"; exit 1; }
[[ -d "$SRC/src/hwsniff" ]] || { echo "Missing $SRC/src/hwsniff"; exit 1; }
[[ -d "$INSTALL_ROOT" ]] || {
  echo "ERROR: $INSTALL_ROOT not found. Run full install first:"
  echo "  sudo bash install-on-pi.sh --no-start"
  exit 1
}

echo "==> Quick update → $INSTALL_ROOT"
# Never wipe .venv. Sync HWSniff tree; update ElaTool vendor separately when present.
rsync -a --delete \
  --exclude '.venv' \
  --exclude '_vendor' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'captures' \
  --exclude 'deploy/dist' \
  "$SRC/" "$INSTALL_ROOT/"

if [[ -d "$SRC/_vendor/ElaTool/src/elatec_uid_tool" ]]; then
  echo "==> Sync ElaTool → $INSTALL_ROOT/_vendor/ElaTool"
  mkdir -p "$INSTALL_ROOT/_vendor"
  rsync -a --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'captures' \
    --exclude '*.egg-info' \
    "$SRC/_vendor/ElaTool/" "$INSTALL_ROOT/_vendor/ElaTool/"
fi

# Ensure packages are importable (editable installs from Full install)
if [[ -x "$INSTALL_ROOT/.venv/bin/pip" ]]; then
  if [[ -d "$INSTALL_ROOT/_vendor/ElaTool" ]]; then
    "$INSTALL_ROOT/.venv/bin/pip" install -e "$INSTALL_ROOT/_vendor/ElaTool" -q
  else
    echo "WARNING: $INSTALL_ROOT/_vendor/ElaTool missing — run Full install"
  fi
  "$INSTALL_ROOT/.venv/bin/pip" install -e "$INSTALL_ROOT" -q
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT"

# Smoke import (must include ElaTool — service crashes without it)
sudo -u "$SERVICE_USER" "$INSTALL_ROOT/.venv/bin/python" - <<'PY'
import hwsniff
import elatec_uid_tool.ntag
from hwsniff.gpio_backend import GpioZeroBackend
print("hwsniff ok:", hwsniff.__file__)
print("elatec_uid_tool ok:", elatec_uid_tool.ntag.__file__)
PY

if [[ "$RESTART" == "1" ]]; then
  if systemctl is-enabled hwsniff >/dev/null 2>&1 || systemctl cat hwsniff >/dev/null 2>&1; then
    echo "==> Restarting hwsniff"
    systemctl restart hwsniff || systemctl start hwsniff
    sleep 1
    systemctl --no-pager --full status hwsniff || true
  else
    echo "==> hwsniff unit not enabled — start manually: sudo systemctl start hwsniff"
  fi
fi

echo "==> Quick update done"
