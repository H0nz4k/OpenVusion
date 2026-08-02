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
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'captures' \
  --exclude 'deploy/dist' \
  "$SRC/" "$INSTALL_ROOT/"

# Ensure package is importable (editable install already present on full install)
if [[ -x "$INSTALL_ROOT/.venv/bin/pip" ]]; then
  "$INSTALL_ROOT/.venv/bin/pip" install -e "$INSTALL_ROOT" -q
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT"

# Smoke import
sudo -u "$SERVICE_USER" "$INSTALL_ROOT/.venv/bin/python" - <<'PY'
import hwsniff
from hwsniff.gpio_backend import GpioZeroBackend
print("hwsniff ok:", hwsniff.__file__)
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
