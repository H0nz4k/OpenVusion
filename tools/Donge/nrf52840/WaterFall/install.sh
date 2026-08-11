#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/waterfall
DATA_ROOT=/var/lib/waterfall
SERVICE_USER="${SUDO_USER:-$USER}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Spusť přes sudo: sudo ./install.sh"
  exit 1
fi

echo "== WaterFall v0.4.0 =="
echo "User: $SERVICE_USER"

export DEBIAN_FRONTEND=noninteractive
apt update
apt install -y python3 python3-venv python3-pip python3-gpiozero bluez

# tshark je použit jen pro offline PCAP/PCAPNG inspector. Je užitečný, ale
# WaterFall musí běžet i bez něj, proto jeho případný instalační problém
# neblokuje základní RF/BLE monitor.
if ! command -v tshark >/dev/null 2>&1; then
  echo "Instaluji volitelný tshark pro PCAP inspector..."
  apt install -y tshark || echo "VAROVÁNÍ: tshark se nepodařilo nainstalovat; PCAP inspector bude deaktivovaný."
fi

mkdir -p \
  "$APP_DIR" \
  "$DATA_ROOT/captures" \
  "$DATA_ROOT/experiments" \
  "$DATA_ROOT/sessions" \
  "$DATA_ROOT/pcap"

cp -a "$SOURCE_DIR/app" "$SOURCE_DIR/requirements.txt" \
      "$SOURCE_DIR/config.example.json" "$SOURCE_DIR/run_server.py" \
      "$SOURCE_DIR/VERSION" "$SOURCE_DIR/CHANGELOG.md" "$SOURCE_DIR/README.md" \
      "$APP_DIR/"

if [[ ! -f "$APP_DIR/config.json" ]]; then
  cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
  echo "Vytvořen nový $APP_DIR/config.json"
else
  echo "Existující $APP_DIR/config.json zachován."
  echo "POZOR: při upgrade z 0.3.x porovnej nové klíče v config.example.json."
fi

rm -rf "$APP_DIR/.venv"
python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# Pokud repo obsahuje ElaTool, připoj ho do stejného venv automaticky.
ELATOOL_CANDIDATES=(
  "/home/$SERVICE_USER/OpenVusion/tools/ElaTool"
  "$SOURCE_DIR/../../ElaTool"
)
for ELA in "${ELATOOL_CANDIDATES[@]}"; do
  if [[ -f "$ELA/pyproject.toml" || -f "$ELA/setup.py" ]]; then
    echo "Nalezen ElaTool: $ELA"
    "$APP_DIR/.venv/bin/pip" install -e "$ELA" || true
    break
  fi
done

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR" "$DATA_ROOT"

if getent group dialout >/dev/null; then
  usermod -aG dialout "$SERVICE_USER"
fi
if getent group gpio >/dev/null; then
  usermod -aG gpio "$SERVICE_USER"
fi
if getent group bluetooth >/dev/null; then
  usermod -aG bluetooth "$SERVICE_USER" || true
fi

cat > /etc/systemd/system/waterfall.service <<EOF2
[Unit]
Description=WaterFall v0.4.0 - OpenVusion RF research monitor
After=network.target bluetooth.target
Wants=network.target bluetooth.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=WATERFALL_CONFIG=$APP_DIR/config.json
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/run_server.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF2

systemctl daemon-reload
systemctl enable waterfall.service
systemctl restart waterfall.service

echo
echo "Instalace / update hotový."
echo "Config: $APP_DIR/config.json"
echo "Data:   $DATA_ROOT"
echo "Service: sudo systemctl status waterfall --no-pager"
echo "Log:     journalctl -u waterfall -f"
echo "Web:     http://<IP_RPI>:8088/"
echo
echo "Kontrola BLE: bluetoothctl show"
echo "Kontrola RF:  ls -l /dev/serial/by-id/"
echo "Kontrola PCAP: tshark --version"
echo "Po změně skupin dialout/gpio/bluetooth může být vhodný reboot."
