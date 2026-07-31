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
id hwsniff 2>/dev/null || true
echo "groups hwsniff: $(id -nG hwsniff 2>/dev/null || echo n/a)"
echo
echo "--- drm / input ---"
ls -l /dev/dri 2>/dev/null || echo "no /dev/dri"
ls -l /dev/fb0 2>/dev/null || true
echo "SDL_VIDEODRIVER(env unit):"
systemctl show-environment 2>/dev/null | grep -i SDL || true
systemctl cat hwsniff.service 2>/dev/null | grep -E 'SDL_|Supplementary|User=|ExecStart' || true
test -f /etc/hwsniff/display.env && { echo "--- /etc/hwsniff/display.env ---"; cat /etc/hwsniff/display.env; } || true
echo
echo "--- journal (last 60) ---"
journalctl -u hwsniff -n 60 --no-pager 2>/dev/null || true
echo
echo "--- paths ---"
ls -ld /opt/Sniff /etc/hwsniff /var/lib/hwsniff /var/log/hwsniff 2>/dev/null || true
df -h /var/lib/hwsniff 2>/dev/null || df -h /
echo
echo "--- recent app log ---"
tail -n 40 /var/log/hwsniff/hwsniff.log 2>/dev/null || echo "no log yet"
echo
echo "--- pygame smoke (as hwsniff, may fail headless SSH) ---"
if [[ -x /opt/Sniff/.venv/bin/python ]]; then
  sudo -u hwsniff env SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}" \
    /opt/Sniff/.venv/bin/python - <<'PY' 2>&1 || true
import os, traceback
print("SDL_VIDEODRIVER=", os.environ.get("SDL_VIDEODRIVER"))
try:
    import pygame
    pygame.init()
    s = pygame.display.set_mode((480, 320), pygame.FULLSCREEN)
    print("OK driver=", pygame.display.get_driver(), "size=", s.get_size())
    pygame.quit()
except Exception as exc:
    traceback.print_exc()
    print("FAIL", exc)
PY
fi
