#!/usr/bin/env bash
# X11 appliance entrypoint — launched by xinit from hwsniff-x11.service.
# update.sh must never delete this file (it lives in the repo).
set -euo pipefail

# Drop folder for per-tag archives: DDMMYYYY_HH_MM.tar
mkdir -p /home/sniffer/capture
chown hwsniff:hwsniff /home/sniffer/capture 2>/dev/null \
  || chown hwsniff:hwsniff /home/sniffer/capture
chmod 0775 /home/sniffer/capture 2>/dev/null || true

exec /usr/sbin/runuser -u hwsniff -- env \
  HOME=/var/lib/hwsniff \
  XDG_RUNTIME_DIR=/run/hwsniff \
  DISPLAY=:0 \
  SDL_VIDEODRIVER=x11 \
  SDL_AUDIODRIVER=dummy \
  PYTHONUNBUFFERED=1 \
  /opt/Sniff/.venv/bin/python -m hwsniff \
  --config /etc/hwsniff/config.json
