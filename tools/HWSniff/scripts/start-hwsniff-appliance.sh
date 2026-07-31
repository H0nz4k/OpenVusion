#!/usr/bin/env bash
# X11 appliance entrypoint — launched by xinit from hwsniff-x11.service.
# Must not exit before exec: any failure here kills xinit (systemd shows SIGHUP).
set -uo pipefail

# Best-effort drop folder for per-tag archives: DDMMYYYY_HH_MM.tar
# Never abort the UI if this path is missing or not chown-able.
mkdir -p /home/sniffer/capture 2>/dev/null || true
chown hwsniff:hwsniff /home/sniffer/capture 2>/dev/null || true
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
