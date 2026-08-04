#!/usr/bin/env bash
# Safe headless HWSniff GPIO installer for a clean Raspberry Pi OS (Bookworm+).
# Does NOT install Xorg / Waveshare / pygame / framebuffer.
#
# Usage (from unpacked bundle OR OpenVusion repo):
#   sudo bash install-on-pi.sh
#   sudo bash install-on-pi.sh --no-start
#   sudo bash install-on-pi.sh --gpio-test
#   sudo bash tools/HWSniff/deploy/install-on-pi.sh   # from git clone
set -euo pipefail

NO_START=0
DO_ENABLE=0
RUN_GPIO_TEST=0
SKIP_APT=0
FORCE_UNIT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start) NO_START=1; shift ;;
    --enable) DO_ENABLE=1; shift ;;
    --gpio-test) RUN_GPIO_TEST=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    --force-unit) FORCE_UNIT=1; shift ;;
    -h|--help)
      cat <<'EOF'
Safe HWSniff GPIO installer (no Xorg/Waveshare).

  sudo bash install-on-pi.sh              # install, enable+start
  sudo bash install-on-pi.sh --no-start   # install only; NOT enabled (safe reboot)
  sudo bash install-on-pi.sh --enable     # with --no-start: enable but don't start now
  sudo bash install-on-pi.sh --gpio-test  # install + GPIO test + enable+start
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve bundle / repo root:
#  A) unpacked pack:  <bundle>/install-on-pi.sh + tools/HWSniff + tools/ElaTool
#  B) git checkout:   tools/HWSniff/deploy/install-on-pi.sh → repo root
if [[ -d "$SCRIPT_DIR/tools/HWSniff" && -d "$SCRIPT_DIR/tools/ElaTool" ]]; then
  BUNDLE_ROOT="$SCRIPT_DIR"
elif [[ -d "$SCRIPT_DIR/../src/hwsniff" ]]; then
  BUNDLE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
else
  echo "Cannot find tools/HWSniff + tools/ElaTool next to installer." >&2
  echo "Run from unpacked bundle or OpenVusion checkout." >&2
  exit 1
fi

HWSNIFF_SRC="$BUNDLE_ROOT/tools/HWSniff"
ELATOOL_SRC="$BUNDLE_ROOT/tools/ElaTool"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/Sniff}"
CONFIG_DIR="${CONFIG_DIR:-/etc/hwsniff}"
DATA_ROOT="${DATA_ROOT:-/var/lib/hwsniff}"
LOG_ROOT="${LOG_ROOT:-/var/log/hwsniff}"
SERVICE_USER="${SERVICE_USER:-hwsniff}"
LOGIN_USER="${LOGIN_USER:-sniffer}"
EXPORT_MIRROR_ROOT="${EXPORT_MIRROR_ROOT:-/home/${LOGIN_USER}/exports}"

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root: sudo bash install-on-pi.sh"
[[ -d "$HWSNIFF_SRC/src/hwsniff" ]] || die "Missing HWSniff sources at $HWSNIFF_SRC"
[[ -d "$ELATOOL_SRC/src" ]] || die "Missing ElaTool sources at $ELATOOL_SRC"

log "OpenVusion HWSniff GPIO — safe install"
log "bundle : $BUNDLE_ROOT"
log "target : $INSTALL_ROOT"
log "user   : $SERVICE_USER"

# --- 1) packages -----------------------------------------------------------
if [[ "$SKIP_APT" -eq 0 ]]; then
  export DEBIAN_FRONTEND=noninteractive
  log "apt update + packages (python, gpio, serial)"
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python3-gpiozero \
    python3-lgpio \
    gpiod \
    rsync \
    ca-certificates
else
  log "Skipping apt (--skip-apt)"
fi

command -v python3 >/dev/null || die "python3 missing"
command -v rsync >/dev/null || die "rsync missing (install rsync or omit --skip-apt)"

# --- 2) service user -------------------------------------------------------
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  log "Creating system user $SERVICE_USER"
  useradd --system --create-home --home-dir "/home/$SERVICE_USER" \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi
# gpio: LED/button chips; dialout: TWN4 USB ACM + GPIO UART (/dev/serial0)
usermod -aG gpio,dialout "$SERVICE_USER" || true

# --- 3) directories ---------------------------------------------------------
log "Creating directories"
mkdir -p "$INSTALL_ROOT" "$CONFIG_DIR" "$DATA_ROOT/captures" "$DATA_ROOT/export" "$LOG_ROOT"

# --- 4) sync application code ---------------------------------------------
log "Syncing application → $INSTALL_ROOT"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'captures' \
  --exclude '.git' \
  --exclude 'deploy/dist' \
  "$HWSNIFF_SRC/" "$INSTALL_ROOT/"

# Keep a copy of ElaTool next to install for editable pip + future capture
mkdir -p "$INSTALL_ROOT/_vendor"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  "$ELATOOL_SRC/" "$INSTALL_ROOT/_vendor/ElaTool/"

# --- 5) venv ---------------------------------------------------------------
log "Python venv (+ system-site-packages for apt gpiozero/lgpio)"
rm -rf "$INSTALL_ROOT/.venv"
python3 -m venv --system-site-packages "$INSTALL_ROOT/.venv"
# shellcheck disable=SC1091
source "$INSTALL_ROOT/.venv/bin/activate"
pip install -U pip wheel
pip install -e "$INSTALL_ROOT/_vendor/ElaTool"
pip install -e "$INSTALL_ROOT"

# Smoke import (no hardware)
python - <<'PY'
import hwsniff
from hwsniff.state import DeviceState, DipMode
assert DeviceState.READY
assert DeviceState.ERROR2
assert DeviceState.POSITIONING
assert DipMode.MAIN
assert hwsniff.__version__.startswith("2.")
print("import ok:", hwsniff.__version__, hwsniff.__file__)
PY

# --- 6) config (v2 profile required; never silently reuse alpha1 pins) ------
cp "$INSTALL_ROOT/config/config.gpio.example.json" "$CONFIG_DIR/config.json.example"
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  log "Installing default v2 config → $CONFIG_DIR/config.json"
  cp "$INSTALL_ROOT/config/config.gpio.example.json" "$CONFIG_DIR/config.json"
else
  log "Checking existing $CONFIG_DIR/config.json for hardware_profile=v2"
  python3 - <<'PY'
import json, shutil, sys
from pathlib import Path
p = Path("/etc/hwsniff/config.json")
example = Path("/etc/hwsniff/config.json.example")
cfg = json.loads(p.read_text(encoding="utf-8"))
profile = cfg.get("hardware_profile")
gpio = cfg.get("gpio") or {}
legacy_start = (gpio.get("buttons") or {}).get("start") == 17
if profile != "v2" or legacy_start:
    bak = p.with_suffix(".json.alpha1.bak")
    shutil.copy2(p, bak)
    shutil.copy2(example, p)
    print(f"Replaced legacy/non-v2 config; backup → {bak}")
else:
    print("Keeping existing v2 config")
PY
fi

# Runtime dirs for lgpio notify pipes + captures + export mirror
mkdir -p "$DATA_ROOT/captures" "$DATA_ROOT/export" "$LOG_ROOT"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_ROOT" "$LOG_ROOT"

# Mirror export dir: hwsniff writes, login user (sniffer) reads — no 0777
if id "$LOGIN_USER" >/dev/null 2>&1; then
  log "Preparing export mirror → $EXPORT_MIRROR_ROOT (owner $SERVICE_USER:$LOGIN_USER)"
  mkdir -p "$EXPORT_MIRROR_ROOT"
  chown "$SERVICE_USER:$LOGIN_USER" "$EXPORT_MIRROR_ROOT"
  chmod 2775 "$EXPORT_MIRROR_ROOT"
else
  log "Login user $LOGIN_USER missing — skipping mirror dir $EXPORT_MIRROR_ROOT"
fi

# --- 7) config hardening (GPIO long-STOP must never poweroff) --------------
# Remove legacy sudoers from older installs — power is a hardware switch.
if [[ -f /etc/sudoers.d/hwsniff-poweroff ]]; then
  log "Removing legacy /etc/sudoers.d/hwsniff-poweroff"
  rm -f /etc/sudoers.d/hwsniff-poweroff
fi
python3 - <<PY
import json
from pathlib import Path
p = Path("$CONFIG_DIR/config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
cfg["hardware_profile"] = "v2"
shutdown = cfg.setdefault("shutdown", {})
shutdown["enabled"] = False
boot = cfg.setdefault("boot", {})
boot.setdefault("shutdown_arm_seconds", 30)
# START moved pin 29/BCM5 → pin 40/BCM21 (pull-up, OFF=1 ON=0)
buttons = (cfg.setdefault("gpio", {})).setdefault("buttons", {})
old_start = buttons.get("start")
if old_start in (None, 5):
    buttons["start"] = 21
buttons.setdefault("stop", 6)
buttons.setdefault("active_low", True)
buttons.setdefault("pull_up", True)
reader = cfg.setdefault("reader", {})
reader.setdefault("auto_detect", True)
if not reader.get("preferred_serial"):
    reader["preferred_serial"] = "/dev/serial0"
collector = cfg.setdefault("collector", {})
collector.setdefault("export_bundle_root", "/var/lib/hwsniff/export")
collector.setdefault("export_bundle_mirror_root", "$EXPORT_MIRROR_ROOT")
collector.setdefault("include_logs_in_bundle", True)
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(
    f"hardware_profile=v2; shutdown.enabled=false; "
    f"buttons.start={buttons.get('start')} (was {old_start}); "
    f"preferred_serial={reader.get('preferred_serial')}; "
    f"mirror={collector.get('export_bundle_mirror_root')}"
)
PY

# --- 8) systemd unit -------------------------------------------------------
UNIT_SRC="$INSTALL_ROOT/systemd/hwsniff-gpio.service"
UNIT_DST="/etc/systemd/system/hwsniff.service"
if [[ -f "$UNIT_DST" && "$FORCE_UNIT" -eq 0 ]]; then
  log "Unit exists — writing $UNIT_DST.new (use --force-unit to replace)"
  install -m 644 "$UNIT_SRC" "$UNIT_DST.new"
else
  log "Installing systemd unit → $UNIT_DST"
  install -m 644 "$UNIT_SRC" "$UNIT_DST"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT" "$DATA_ROOT" "$LOG_ROOT"
chmod 755 "$INSTALL_ROOT"

systemctl daemon-reload

# --- 9) optional GPIO self-test before enabling service --------------------
if [[ "$RUN_GPIO_TEST" -eq 1 ]]; then
  log "Running GPIO self-test as $SERVICE_USER (LEDs + buttons)"
  echo "    Follow prompts: START then STOP."
  # group membership may need new login — use sg when available
  if command -v sg >/dev/null 2>&1; then
    sg gpio -c "sudo -u $SERVICE_USER $INSTALL_ROOT/.venv/bin/python -m hwsniff --gpio-test --config $CONFIG_DIR/config.json" \
      || die "GPIO test failed — service NOT started. Fix wiring and re-run with --gpio-test"
  else
    sudo -u "$SERVICE_USER" "$INSTALL_ROOT/.venv/bin/python" -m hwsniff \
      --gpio-test --config "$CONFIG_DIR/config.json" \
      || die "GPIO test failed — service NOT started"
  fi
fi

# --- 10) enable / start ----------------------------------------------------
# IMPORTANT: --no-start must NOT auto-enable. Old behaviour enabled the unit,
# so the next reboot started hwsniff and a stuck STOP could poweroff the Pi.
if [[ "$NO_START" -eq 1 && "$DO_ENABLE" -eq 0 && "$RUN_GPIO_TEST" -eq 0 ]]; then
  systemctl disable hwsniff.service 2>/dev/null || true
  systemctl stop hwsniff.service 2>/dev/null || true
  log "Installed with --no-start → service DISABLED (reboot will NOT start hwsniff)"
elif [[ "$NO_START" -eq 1 && "$DO_ENABLE" -eq 1 ]]; then
  systemctl enable hwsniff.service
  systemctl stop hwsniff.service 2>/dev/null || true
  log "Installed with --no-start --enable → enabled, not started now"
else
  systemctl enable hwsniff.service
  log "Starting hwsniff.service"
  systemctl restart hwsniff.service || systemctl start hwsniff.service
  sleep 1
  systemctl --no-pager --full status hwsniff.service || true
fi

cat <<EOF

========================================================================
 HWSniff GPIO install complete
========================================================================
  App:     $INSTALL_ROOT
  Config:  $CONFIG_DIR/config.json
  Data:    $DATA_ROOT
  Export:  $DATA_ROOT/export  (+ mirror $EXPORT_MIRROR_ROOT)
  Logs:    journalctl -u hwsniff -f

  Status:  systemctl status hwsniff
  Stop:    sudo systemctl stop hwsniff
  Test:    sudo -u $SERVICE_USER $INSTALL_ROOT/.venv/bin/python -m hwsniff --gpio-test

  UART (ELATEC TWN4 COM1 @ 9600 8N1 on /dev/serial0):
    - /boot/firmware/config.txt: enable_uart=1
    - remove console=serial0,115200 from cmdline.txt
    - HOSTSENSE → GND (COM1); stop hwsniff before manual UART tests

  Safe bring-up (recommended):
    1) sudo reboot                          # groups / gpio / dialout
    2) cd /var/lib/hwsniff
       sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --diagnostics
    3) cd /var/lib/hwsniff
       sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
    4) DIP1+DIP2 OFF; check STOP wiring (BCM GPIO6 / pin 31)
    5) sudo systemctl enable --now hwsniff

  Note: WorkingDirectory=/var/lib/hwsniff (lgpio runtime).
        Never run GPIO CLI from /opt/Sniff as cwd (not writable).
        App also chdirs to data_root automatically.
        STOP = cooperative cancel. Power is a hardware switch.
        GPIO v2: 40 START, 31 STOP, 32 DIP1, 33 DIP2,
                 35 GREEN, 36 YELLOW, 37 RED, 38 BLUE.
========================================================================
EOF
