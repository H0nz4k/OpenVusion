#!/usr/bin/env bash
# Headless Pi Zero 2 W installer — NO Xorg / Waveshare / pygame / framebuffer.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HWSNIFF_SRC="$ROOT/tools/HWSniff"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/Sniff}"
CONFIG_DIR="${CONFIG_DIR:-/etc/hwsniff}"
DATA_ROOT="${DATA_ROOT:-/var/lib/hwsniff}"
LOG_ROOT="${LOG_ROOT:-/var/log/hwsniff}"
SERVICE_USER="${SERVICE_USER:-hwsniff}"

echo "==> OpenVusion HWSniff GPIO install (Pi Zero 2 W)"
echo "    source: $HWSNIFF_SRC"
echo "    target: $INSTALL_ROOT"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash tools/HWSniff/install-gpio.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-gpiozero \
  python3-lgpio \
  gpiod \
  git

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/"$SERVICE_USER" \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi
usermod -aG gpio,dialout "$SERVICE_USER" || true

mkdir -p "$INSTALL_ROOT" "$CONFIG_DIR" "$DATA_ROOT" "$DATA_ROOT/captures" "$LOG_ROOT"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude '.git' \
  "$HWSNIFF_SRC/" "$INSTALL_ROOT/"

# Editable install of HWSniff + ElaTool (for alpha2 capture)
python3 -m venv "$INSTALL_ROOT/.venv"
# system site packages help pick up apt gpiozero/lgpio on Bookworm
if [[ -f /usr/lib/python3*/dist-packages/gpiozero/__init__.py ]] || \
   ls /usr/lib/python3*/dist-packages/gpiozero >/dev/null 2>&1; then
  # recreate with --system-site-packages if gpiozero from apt
  rm -rf "$INSTALL_ROOT/.venv"
  python3 -m venv --system-site-packages "$INSTALL_ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$INSTALL_ROOT/.venv/bin/activate"
pip install -U pip
pip install -e "$ROOT/tools/ElaTool"
pip install -e "$INSTALL_ROOT"

if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  cp "$INSTALL_ROOT/config/config.gpio.example.json" "$CONFIG_DIR/config.json"
fi

install -m 644 "$INSTALL_ROOT/systemd/hwsniff-gpio.service" \
  /etc/systemd/system/hwsniff.service

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT" "$DATA_ROOT" "$LOG_ROOT"
chmod 755 "$INSTALL_ROOT"

systemctl daemon-reload
systemctl enable hwsniff.service
systemctl restart hwsniff.service || systemctl start hwsniff.service

echo "==> Done."
echo "    status:  systemctl status hwsniff"
echo "    gpio:    sudo -u $SERVICE_USER $INSTALL_ROOT/.venv/bin/python -m hwsniff --gpio-test"
echo "    logs:    journalctl -u hwsniff -f"
echo "    NOTE: Waveshare/X11/pygame were NOT installed."
