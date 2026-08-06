#!/usr/bin/env bash
set -euo pipefail

SKIP_DISPLAY=0
CONFIGURE_DISPLAY=0
NO_START=0
FORCE_UNIT=0
X11_UNIT=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HWSNIFF_SRC="$(cd "$(dirname "$0")" && pwd)"
ELATOOL_SRC="${REPO_ROOT}/tools/ElaTool"
PREFIX="/opt/Sniff"
CONFIG_DIR="/etc/hwsniff"
DATA_ROOT="/var/lib/hwsniff"
LOG_ROOT="/var/log/hwsniff"
USER_NAME="hwsniff"

for arg in "$@"; do
  case "$arg" in
    --skip-display-config) SKIP_DISPLAY=1 ;;
    --configure-display) CONFIGURE_DISPLAY=1 ;;
    --no-start) NO_START=1 ;;
    --force-unit) FORCE_UNIT=1 ;;
    --x11-unit) X11_UNIT=1 ;;
    -h|--help)
      echo "Usage: sudo bash install.sh [options]"
      echo "  --skip-display-config  Do not touch display overlays"
      echo "  --configure-display    Print display guidance only"
      echo "  --no-start             Install but do not start service"
      echo "  --force-unit           Overwrite existing systemd unit (DANGEROUS)"
      echo "  --x11-unit             Install Waveshare xinit/X11 unit template"
      echo
      echo "For day-to-day updates use update.sh — NOT this installer."
      exit 0
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash install.sh"
  exit 1
fi

if [[ ! -f /etc/os-release ]]; then
  echo "Unsupported system (missing /etc/os-release)"
  exit 1
fi
# shellcheck source=/dev/null
. /etc/os-release
echo "Detected OS: ${PRETTY_NAME:-unknown}"

if ! command -v python3 >/dev/null; then
  echo "python3 is required"
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv python3-pip python3-dev \
  libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
  pkg-config || true

if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/hwsniff --shell /usr/sbin/nologin "${USER_NAME}"
fi
usermod -aG dialout,video,render,input "${USER_NAME}" 2>/dev/null || usermod -aG dialout,video,input "${USER_NAME}" || true

mkdir -p "${PREFIX}" "${CONFIG_DIR}" "${DATA_ROOT}/captures" "${LOG_ROOT}" /run/hwsniff
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'vendor' \
  --exclude '_vendor' \
  "${HWSNIFF_SRC}/" "${PREFIX}/"

# Canonical ElaTool path matches deploy/ (_vendor). Mirror to vendor/ for compat.
mkdir -p "${PREFIX}/_vendor" "${PREFIX}/vendor"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude '*.pyc' \
  --exclude '*.egg-info' \
  "${ELATOOL_SRC}/" "${PREFIX}/_vendor/ElaTool/"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude '*.pyc' \
  --exclude '*.egg-info' \
  "${ELATOOL_SRC}/" "${PREFIX}/vendor/ElaTool/"

python3 -m venv "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/pip" install --upgrade pip
"${PREFIX}/.venv/bin/pip" install -e "${PREFIX}/_vendor/ElaTool"
"${PREFIX}/.venv/bin/pip" install -e "${PREFIX}"

if [[ -f "${CONFIG_DIR}/config.json" ]]; then
  cp -a "${CONFIG_DIR}/config.json" "${CONFIG_DIR}/config.json.bak.$(date +%Y%m%d%H%M%S)"
  cp -a "${PREFIX}/config/config.example.json" "${CONFIG_DIR}/config.json.new"
  echo "Kept existing config; wrote config.json.new"
else
  cp -a "${PREFIX}/config/config.example.json" "${CONFIG_DIR}/config.json"
fi
cp -a "${PREFIX}/config/config.example.json" "${CONFIG_DIR}/config.example.json"

# Drop folder for per-capture ZIP bundles (hwsniff must be able to write).
EXPORT_CAPTURE_ROOT="/home/sniffer/capture"
mkdir -p "${EXPORT_CAPTURE_ROOT}"
if id sniffer >/dev/null 2>&1; then
  chown sniffer:sniffer /home/sniffer 2>/dev/null || true
  chown sniffer:"${USER_NAME}" "${EXPORT_CAPTURE_ROOT}" 2>/dev/null \
    || chown "${USER_NAME}:${USER_NAME}" "${EXPORT_CAPTURE_ROOT}"
  chmod 0775 "${EXPORT_CAPTURE_ROOT}"
  # Ensure hwsniff can create DDMMYYYY_HH_MM folders.
  usermod -aG sniffer "${USER_NAME}" 2>/dev/null || true
else
  chown "${USER_NAME}:${USER_NAME}" "${EXPORT_CAPTURE_ROOT}"
  chmod 0775 "${EXPORT_CAPTURE_ROOT}"
fi

chown -R "${USER_NAME}:${USER_NAME}" "${DATA_ROOT}" "${LOG_ROOT}"
chown -R root:root "${PREFIX}"
chmod 755 "${PREFIX}/scripts/"*.sh 2>/dev/null || true

UNIT_SRC="${PREFIX}/systemd/hwsniff.service"
if [[ "${X11_UNIT}" -eq 1 ]]; then
  UNIT_SRC="${PREFIX}/systemd/hwsniff-x11.service"
fi

# Never silently overwrite a working appliance unit (xinit/X11).
if [[ -f /etc/systemd/system/hwsniff.service && "${FORCE_UNIT}" -eq 0 ]]; then
  echo "Keeping existing /etc/systemd/system/hwsniff.service (not overwritten)."
  echo "Templates are in ${PREFIX}/systemd/ (hwsniff.service, hwsniff-x11.service)."
  echo "To replace intentionally: sudo bash install.sh --force-unit [--x11-unit]"
else
  if [[ -f /etc/systemd/system/hwsniff.service ]]; then
    cp -a /etc/systemd/system/hwsniff.service \
      "/etc/systemd/system/hwsniff.service.bak.$(date +%Y%m%d%H%M%S)"
  fi
  install -m 0644 "${UNIT_SRC}" /etc/systemd/system/hwsniff.service
  systemctl daemon-reload
fi

# Optional SDL override file — never overwritten if it already exists.
if [[ ! -f /etc/hwsniff/display.env ]]; then
  cat >/etc/hwsniff/display.env <<'EOF'
# Optional SDL overrides for HWSniff (not wiped by update.sh).
# Examples:
# SDL_VIDEODRIVER=kmsdrm
# SDL_VIDEODRIVER=x11
# SDL_VIDEODRIVER=fbcon
EOF
  chmod 644 /etc/hwsniff/display.env
fi
systemctl daemon-reload
systemctl enable hwsniff.service

if [[ "${CONFIGURE_DISPLAY}" -eq 1 && "${SKIP_DISPLAY}" -eq 0 ]]; then
  echo "Display configuration is parameterized — no Waveshare overlay guessed."
  echo "Follow vendor docs for Waveshare 3.5 LCD (B), then reboot manually."
fi

if [[ "${NO_START}" -eq 0 ]]; then
  systemctl restart hwsniff.service || systemctl start hwsniff.service || true
fi

"${PREFIX}/scripts/diagnose.sh" || true
echo
echo "Install complete. Application: ${PREFIX}"
echo "Config: ${CONFIG_DIR}/config.json"
echo "Data: ${DATA_ROOT}"
echo "Reboot is NOT automatic."
