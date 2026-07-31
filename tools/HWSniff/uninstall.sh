#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi
systemctl disable --now hwsniff.service 2>/dev/null || true
rm -f /etc/systemd/system/hwsniff.service
systemctl daemon-reload
rm -rf /opt/Sniff
echo "Removed /opt/Sniff and service. Data in /var/lib/hwsniff kept."
echo "Config in /etc/hwsniff kept. Remove manually if desired."
