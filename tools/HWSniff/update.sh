#!/usr/bin/env bash
# Lightweight update after `git pull` — sync code + restart service.
# Does NOT run apt-get, recreate users, or reconfigure the display.
# Does NOT overwrite systemd unit unless --update-unit is passed.
# For a full (re)install use: sudo bash install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HWSNIFF_SRC="$(cd "$(dirname "$0")" && pwd)"
ELATOOL_SRC="${REPO_ROOT}/tools/ElaTool"
PREFIX="/opt/Sniff"
RESTART=1
REINSTALL_DEPS=0
UPDATE_UNIT=0

for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0 ;;
    --reinstall-deps) REINSTALL_DEPS=1 ;;
    --update-unit) UPDATE_UNIT=1 ;;
    -h|--help)
      echo "Usage: sudo bash update.sh [--no-restart] [--reinstall-deps] [--update-unit]"
      echo
      echo "After git pull on the Pi:"
      echo "  cd /path/to/OpenVusion && git pull"
      echo "  sudo bash tools/HWSniff/update.sh"
      echo
      echo "Syncs code into ${PREFIX} and restarts hwsniff.service."
      echo "By default does NOT rewrite /etc/systemd/system/hwsniff.service"
      echo "(pass --update-unit only when you intentionally want the template)."
      exit 0
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash update.sh"
  exit 1
fi

if [[ ! -d "${PREFIX}" ]]; then
  echo "${PREFIX} not found. Run first-time install:"
  echo "  sudo bash ${HWSNIFF_SRC}/install.sh"
  exit 1
fi

if [[ ! -x "${PREFIX}/.venv/bin/python" ]]; then
  echo "Missing ${PREFIX}/.venv — run full install.sh once."
  exit 1
fi

echo "Syncing HWSniff → ${PREFIX}"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'vendor' \
  "${HWSNIFF_SRC}/" "${PREFIX}/"

if [[ -d "${ELATOOL_SRC}" ]]; then
  echo "Syncing ElaTool → ${PREFIX}/vendor/ElaTool"
  mkdir -p "${PREFIX}/vendor"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude 'captures' \
    --exclude '*.pyc' \
    "${ELATOOL_SRC}/" "${PREFIX}/vendor/ElaTool/"
fi

if [[ -f "${PREFIX}/config/config.example.json" ]]; then
  mkdir -p /etc/hwsniff
  cp -a "${PREFIX}/config/config.example.json" /etc/hwsniff/config.example.json
fi

chmod 755 "${PREFIX}/scripts/"*.sh 2>/dev/null || true

# Ensure service user can open DRM / serial / touch (idempotent).
if id hwsniff >/dev/null 2>&1; then
  usermod -aG dialout,video,render,input hwsniff 2>/dev/null \
    || usermod -aG dialout,video,input hwsniff || true
fi

if [[ "${REINSTALL_DEPS}" -eq 1 ]]; then
  echo "Reinstalling Python packages into venv…"
  "${PREFIX}/.venv/bin/pip" install -e "${PREFIX}/vendor/ElaTool"
  "${PREFIX}/.venv/bin/pip" install -e "${PREFIX}"
fi

if [[ "${UPDATE_UNIT}" -eq 1 ]]; then
  echo "Updating systemd unit from template…"
  install -m 0644 "${PREFIX}/systemd/hwsniff.service" /etc/systemd/system/hwsniff.service
  systemctl daemon-reload
fi

if [[ "${RESTART}" -eq 1 ]]; then
  echo "Restarting hwsniff…"
  systemctl restart hwsniff.service
  sleep 1
  systemctl --no-pager --full status hwsniff.service || true
  echo
  echo "If UI is black, check:"
  echo "  journalctl -u hwsniff -n 80 --no-pager"
  echo "  tail -n 40 /var/log/hwsniff/hwsniff.log"
fi

echo "Update complete. Config left at /etc/hwsniff/config.json"
