#!/usr/bin/env bash
# SAFE code update after `git pull`.
#
# NEVER touches:
#   - apt / system packages
#   - /etc/systemd/system/hwsniff.service  (unless you pass --update-unit)
#   - /etc/hwsniff/config.json
#   - display / Xorg / dtoverlay
#
# By default only syncs Python/app code into /opt/Sniff and restarts the
# *already installed* unit (whatever ExecStart you tuned — xinit or not).
#
# Ultra-safe (no restart, no usermod):
#   sudo bash tools/HWSniff/update.sh --code-only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HWSNIFF_SRC="$(cd "$(dirname "$0")" && pwd)"
ELATOOL_SRC="${REPO_ROOT}/tools/ElaTool"
PREFIX="/opt/Sniff"
RESTART=1
REINSTALL_DEPS=0
UPDATE_UNIT=0
CODE_ONLY=0
TOUCH_USER=1

for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0 ;;
    --code-only)
      CODE_ONLY=1
      RESTART=0
      TOUCH_USER=0
      UPDATE_UNIT=0
      ;;
    --reinstall-deps) REINSTALL_DEPS=1 ;;
    --update-unit) UPDATE_UNIT=1 ;;
    -h|--help)
      cat <<EOF
Usage: sudo bash update.sh [--code-only] [--no-restart] [--reinstall-deps] [--update-unit]

SAFE default (recommended on a working Pi):
  cd /opt/OpenVusion
  sudo git pull --ff-only
  sudo bash tools/HWSniff/update.sh --code-only
  # or one shot:
  sudo bash tools/HWSniff/safe-update.sh --restart

What this script does NOT do by default:
  - apt-get / system package updates
  - overwrite /etc/systemd/system/hwsniff.service
  - change /etc/hwsniff/config.json
  - reconfigure display / Xorg

--code-only     Sync code only (no restart, no usermod, never unit)
--no-restart    Sync code, leave service running (restart yourself)
--update-unit   DANGEROUS on Waveshare/X11: installs template unit from repo
--reinstall-deps  also upgrade pip/wheel (editable ElaTool+HWSniff always reinstalled)
EOF
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

echo "=== HWSniff safe update ==="
echo "Source:  ${HWSNIFF_SRC}"
echo "Target:  ${PREFIX}"
if [[ -f /etc/systemd/system/hwsniff.service ]]; then
  echo "Unit:    /etc/systemd/system/hwsniff.service (will NOT be overwritten)"
  grep -E '^ExecStart=' /etc/systemd/system/hwsniff.service || true
else
  echo "Unit:    (none installed yet)"
fi
echo

echo "Syncing HWSniff → ${PREFIX}"
# Keep local appliance extras that may exist only on the Pi.
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'captures' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'vendor' \
  --exclude '_vendor' \
  --exclude 'scripts/local/' \
  "${HWSNIFF_SRC}/" "${PREFIX}/"

# Canonical ElaTool tree for the appliance venv (same path as deploy/).
# Older installs used vendor/ElaTool; keep syncing both during transition, but
# always (re)install editable from _vendor so FeliCa auto-dispatch is live.
if [[ -d "${ELATOOL_SRC}" ]]; then
  echo "Syncing ElaTool → ${PREFIX}/_vendor/ElaTool"
  mkdir -p "${PREFIX}/_vendor"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude 'captures' \
    --exclude '*.pyc' \
    --exclude '*.egg-info' \
    "${ELATOOL_SRC}/" "${PREFIX}/_vendor/ElaTool/"
  # Compatibility mirror for docs/scripts that still mention vendor/
  mkdir -p "${PREFIX}/vendor"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude 'captures' \
    --exclude '*.pyc' \
    --exclude '*.egg-info' \
    "${ELATOOL_SRC}/" "${PREFIX}/vendor/ElaTool/"
fi

if [[ -f "${PREFIX}/config/config.example.json" ]]; then
  mkdir -p /etc/hwsniff
  cp -a "${PREFIX}/config/config.example.json" /etc/hwsniff/config.example.json
fi

# Ensure appliance wrapper exists even if an older tree lacked it.
if [[ ! -f "${PREFIX}/scripts/start-hwsniff-appliance.sh" ]]; then
  echo "ERROR: missing ${PREFIX}/scripts/start-hwsniff-appliance.sh after sync"
  exit 1
fi
chmod 755 "${PREFIX}/scripts/"*.sh 2>/dev/null || true

if [[ "${TOUCH_USER}" -eq 1 ]] && id hwsniff >/dev/null 2>&1; then
  usermod -aG dialout,video,render,input hwsniff 2>/dev/null \
    || usermod -aG dialout,video,input hwsniff || true
fi

# Deterministic: point venv at the freshly synced ElaTool (FeliCa modules).
# --reinstall-deps additionally upgrades pip tooling; editable install is always done.
if [[ -x "${PREFIX}/.venv/bin/pip" ]]; then
  if [[ "${REINSTALL_DEPS}" -eq 1 ]]; then
    echo "Upgrading pip tooling…"
    "${PREFIX}/.venv/bin/pip" install -U pip wheel
  fi
  if [[ -d "${PREFIX}/_vendor/ElaTool" ]]; then
    echo "Installing ElaTool editable from _vendor (FeliCa-capable)…"
    "${PREFIX}/.venv/bin/pip" install -e "${PREFIX}/_vendor/ElaTool" -q
  elif [[ -d "${PREFIX}/vendor/ElaTool" ]]; then
    echo "WARNING: only legacy vendor/ElaTool present — installing from there"
    "${PREFIX}/.venv/bin/pip" install -e "${PREFIX}/vendor/ElaTool" -q
  else
    echo "ERROR: ElaTool vendor tree missing under ${PREFIX}/_vendor or vendor"
    exit 1
  fi
  echo "Installing HWSniff editable…"
  "${PREFIX}/.venv/bin/pip" install -e "${PREFIX}" -q
fi

# Smoke: shared capture must expose technology-aware CaptureProbe + FeliCa helpers.
"${PREFIX}/.venv/bin/python" - <<'PY'
from elatec_uid_tool.readonly_capture import CaptureProbe, AutoCaptureProbe
import elatec_uid_tool.readonly_capture.felica as felica
import hwsniff
assert CaptureProbe is AutoCaptureProbe
assert hasattr(felica, "felica_poll")
assert hasattr(felica, "request_service_diag")
print("smoke ok:", hwsniff.__version__, CaptureProbe.__name__)
PY

if [[ "${UPDATE_UNIT}" -eq 1 ]]; then
  echo
  echo "WARNING: --update-unit will overwrite /etc/systemd/system/hwsniff.service"
  echo "Your working xinit/X11 unit will be replaced by the repo template."
  echo "Prefer copying systemd/hwsniff-x11.service manually if needed."
  if [[ -f /etc/systemd/system/hwsniff.service ]]; then
    bak="/etc/systemd/system/hwsniff.service.bak.$(date +%Y%m%d%H%M%S)"
    cp -a /etc/systemd/system/hwsniff.service "${bak}"
    echo "Backup: ${bak}"
  fi
  install -m 0644 "${PREFIX}/systemd/hwsniff.service" /etc/systemd/system/hwsniff.service
  systemctl daemon-reload
fi

if [[ "${RESTART}" -eq 1 ]]; then
  echo "Restarting hwsniff (unit file unchanged)…"
  systemctl restart hwsniff.service
  sleep 1
  systemctl --no-pager --full status hwsniff.service || true
else
  echo
  echo "Code synced. Service NOT restarted."
  if [[ "${CODE_ONLY}" -eq 1 ]]; then
    echo "When you want the new code:"
    echo "  sudo systemctl restart hwsniff"
  fi
fi

echo
echo "Update complete."
echo "  config:  /etc/hwsniff/config.json  (untouched)"
echo "  unit:    /etc/systemd/system/hwsniff.service  (untouched unless --update-unit)"
echo "  wrapper: ${PREFIX}/scripts/start-hwsniff-appliance.sh"
