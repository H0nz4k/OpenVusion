#!/usr/bin/env bash
set -euo pipefail
echo "=== HWSniff diagnose ==="
echo "date: $(date -Is 2>/dev/null || date)"
echo "uname: $(uname -a)"
command -v python3 >/dev/null && python3 --version || true
echo
echo "--- USB ---"
lsusb 2>/dev/null || echo "lsusb unavailable"
echo
echo "--- serial ports ---"
if [[ -x /opt/Sniff/.venv/bin/python ]]; then
  /opt/Sniff/.venv/bin/python -m serial.tools.list_ports -v || true
else
  python3 -m serial.tools.list_ports -v 2>/dev/null || true
fi
echo
echo "--- service ---"
systemctl is-enabled hwsniff.service 2>/dev/null || true
systemctl is-active hwsniff.service 2>/dev/null || true
echo
echo "--- paths ---"
ls -ld /opt/Sniff /etc/hwsniff /var/lib/hwsniff /var/log/hwsniff 2>/dev/null || true
df -h /var/lib/hwsniff 2>/dev/null || df -h /
echo
echo "--- recent log ---"
tail -n 40 /var/log/hwsniff/hwsniff.log 2>/dev/null || echo "no log yet"
