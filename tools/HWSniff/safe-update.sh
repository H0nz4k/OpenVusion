#!/usr/bin/env bash
# Appliance-safe updater for Raspberry Pi HWSniff.
#
#   sudo bash tools/HWSniff/safe-update.sh
#   sudo bash tools/HWSniff/safe-update.sh --restart
#
# Does:
#   1) snapshot protected system files
#   2) sudo git pull --ff-only (script is root; pull runs as root)
#   3) code-only sync into /opt/Sniff  (never apt, never unit rewrite)
#   4) verify protected files unchanged + appliance wrapper present
#   5) restore unit from snapshot if somehow altered
#   6) optional service restart only when checks pass
#
# Never runs install.sh. Never passes --update-unit / --force-unit.
set -euo pipefail

HWSNIFF_SRC="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${HWSNIFF_SRC}/../.." && pwd)"
PREFIX="/opt/Sniff"
UNIT_PATH="/etc/systemd/system/hwsniff.service"
CONFIG_PATH="/etc/hwsniff/config.json"
DISPLAY_ENV="/etc/hwsniff/display.env"
WRAPPER_REL="scripts/start-hwsniff-appliance.sh"
WRAPPER_PATH="${PREFIX}/${WRAPPER_REL}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/var/lib/hwsniff/update-backups/${STAMP}"
DO_RESTART=0
DO_PULL=1
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --restart) DO_RESTART=1 ;;
    --no-pull) DO_PULL=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      cat <<EOF
Usage: sudo bash safe-update.sh [--restart] [--no-pull] [--dry-run]

Safe Pi updater:
  - git pull OpenVusion repo
  - sync HWSniff + ElaTool code into /opt/Sniff
  - refuse to leave you with a broken xinit/X11 appliance

Protected (must stay identical across update):
  ${UNIT_PATH}
  ${CONFIG_PATH}
  ${DISPLAY_ENV}   (if present)

Required after sync:
  ${WRAPPER_PATH}
  unit ExecStart must still look like your appliance
  (xinit + start-hwsniff-appliance.sh), if it did before.

Options:
  --restart   restart hwsniff only after all checks pass
  --no-pull   skip git pull (sync already-pulled tree)
  --dry-run   show plan / current checks, change nothing
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (see --help)"
      exit 2
      ;;
  esac
done

log() { echo "[safe-update] $*"; }
die() { echo "[safe-update] ERROR: $*" >&2; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "run as root: sudo bash tools/HWSniff/safe-update.sh"
  fi
}

sha_file() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    sha256sum "${path}" | awk '{print $1}'
  else
    echo "MISSING"
  fi
}

snapshot_protected() {
  mkdir -p "${BACKUP_DIR}"
  local f
  for f in "${UNIT_PATH}" "${CONFIG_PATH}" "${DISPLAY_ENV}"; do
    if [[ -f "${f}" ]]; then
      cp -a "${f}" "${BACKUP_DIR}/"
    fi
  done
  if [[ -f "${WRAPPER_PATH}" ]]; then
    mkdir -p "${BACKUP_DIR}/opt-scripts"
    cp -a "${WRAPPER_PATH}" "${BACKUP_DIR}/opt-scripts/"
  fi
  {
    echo "stamp=${STAMP}"
    echo "unit_sha=$(sha_file "${UNIT_PATH}")"
    echo "config_sha=$(sha_file "${CONFIG_PATH}")"
    echo "display_env_sha=$(sha_file "${DISPLAY_ENV}")"
    echo "wrapper_sha=$(sha_file "${WRAPPER_PATH}")"
    if [[ -f "${UNIT_PATH}" ]]; then
      echo "----- unit Exec* -----"
      grep -E '^(ExecStart|ExecStartPre|User|Group)=' "${UNIT_PATH}" || true
    fi
  } >"${BACKUP_DIR}/manifest.txt"
  log "Snapshot → ${BACKUP_DIR}"
}

unit_is_x11_appliance() {
  [[ -f "${UNIT_PATH}" ]] || return 1
  grep -q 'xinit' "${UNIT_PATH}" \
    && grep -q 'start-hwsniff-appliance\.sh' "${UNIT_PATH}"
}

unit_is_direct_python() {
  [[ -f "${UNIT_PATH}" ]] || return 1
  grep -qE 'ExecStart=.*/\.venv/bin/python -m hwsniff' "${UNIT_PATH}" \
    && ! grep -q 'xinit' "${UNIT_PATH}"
}

print_unit_summary() {
  if [[ ! -f "${UNIT_PATH}" ]]; then
    log "unit: MISSING"
    return
  fi
  log "unit ExecStart:"
  grep -E '^ExecStart=' "${UNIT_PATH}" | sed 's/^/  /' || true
  if unit_is_x11_appliance; then
    log "unit profile: X11/xinit appliance (good)"
  elif unit_is_direct_python; then
    log "unit profile: direct python (no xinit) — OK only if that is intentional"
  else
    log "unit profile: custom"
  fi
}

git_pull() {
  [[ "${DO_PULL}" -eq 1 ]] || { log "Skipping git pull (--no-pull)"; return; }
  [[ -d "${REPO_ROOT}/.git" ]] || die "not a git repo: ${REPO_ROOT}"

  # On this appliance the OpenVusion tree is updated as root.
  # Equivalent to: sudo git pull --ff-only
  log "sudo git pull --ff-only in ${REPO_ROOT}"
  if ! git -C "${REPO_ROOT}" pull --ff-only; then
    die "git pull --ff-only failed (commit/stash local changes, or fix conflicts)"
  fi
  git -C "${REPO_ROOT}" log -1 --oneline | sed 's/^/[safe-update] HEAD /'
}

sync_code() {
  log "Syncing code (update.sh --code-only)…"
  bash "${HWSNIFF_SRC}/update.sh" --code-only
}

verify_and_heal() {
  local ok=1
  local before_unit after_unit before_cfg after_cfg

  before_unit="$(awk -F= '/^unit_sha=/{print $2}' "${BACKUP_DIR}/manifest.txt")"
  before_cfg="$(awk -F= '/^config_sha=/{print $2}' "${BACKUP_DIR}/manifest.txt")"
  after_unit="$(sha_file "${UNIT_PATH}")"
  after_cfg="$(sha_file "${CONFIG_PATH}")"

  if [[ "${before_unit}" != "MISSING" && "${after_unit}" != "${before_unit}" ]]; then
    log "Unit file CHANGED unexpectedly — restoring snapshot"
    cp -a "${BACKUP_DIR}/$(basename "${UNIT_PATH}")" "${UNIT_PATH}"
    systemctl daemon-reload
    after_unit="$(sha_file "${UNIT_PATH}")"
    if [[ "${after_unit}" != "${before_unit}" ]]; then
      die "failed to restore ${UNIT_PATH}"
    fi
    log "Unit restored from ${BACKUP_DIR}"
  else
    log "Unit unchanged ✓"
  fi

  if [[ "${before_cfg}" != "MISSING" && "${after_cfg}" != "${before_cfg}" ]]; then
    log "Config CHANGED unexpectedly — restoring snapshot"
    cp -a "${BACKUP_DIR}/$(basename "${CONFIG_PATH}")" "${CONFIG_PATH}"
    after_cfg="$(sha_file "${CONFIG_PATH}")"
    [[ "${after_cfg}" == "${before_cfg}" ]] || die "failed to restore config"
    log "Config restored ✓"
  else
    log "Config unchanged ✓"
  fi

  if [[ -f "${BACKUP_DIR}/$(basename "${DISPLAY_ENV}")" ]]; then
    local before_de after_de
    before_de="$(awk -F= '/^display_env_sha=/{print $2}' "${BACKUP_DIR}/manifest.txt")"
    after_de="$(sha_file "${DISPLAY_ENV}")"
    if [[ "${before_de}" != "MISSING" && "${after_de}" != "${before_de}" ]]; then
      log "display.env CHANGED — restoring"
      cp -a "${BACKUP_DIR}/$(basename "${DISPLAY_ENV}")" "${DISPLAY_ENV}"
    else
      log "display.env unchanged ✓"
    fi
  fi

  # Appliance wrapper must exist after sync (shipped in repo).
  if [[ ! -x "${WRAPPER_PATH}" ]]; then
    if [[ -f "${HWSNIFF_SRC}/${WRAPPER_REL}" ]]; then
      log "Wrapper missing/not executable — copying from repo"
      install -m 0755 "${HWSNIFF_SRC}/${WRAPPER_REL}" "${WRAPPER_PATH}"
    elif [[ -f "${BACKUP_DIR}/opt-scripts/start-hwsniff-appliance.sh" ]]; then
      log "Wrapper missing — restoring from snapshot"
      install -m 0755 \
        "${BACKUP_DIR}/opt-scripts/start-hwsniff-appliance.sh" \
        "${WRAPPER_PATH}"
    else
      die "missing ${WRAPPER_PATH}"
    fi
  fi
  log "Wrapper OK ✓  ${WRAPPER_PATH}"

  # If the live unit is the X11 appliance, enforce invariants.
  if unit_is_x11_appliance; then
    grep -q 'start-hwsniff-appliance\.sh' "${UNIT_PATH}" || ok=0
    [[ -x "${WRAPPER_PATH}" ]] || ok=0
    if grep -qE 'ExecStart=.*/\.venv/bin/python -m hwsniff' "${UNIT_PATH}" \
      && ! grep -q 'xinit' "${UNIT_PATH}"; then
      ok=0
    fi
    [[ "${ok}" -eq 1 ]] || die "X11 appliance invariants failed"
    log "X11 appliance invariants OK ✓"
  elif unit_is_direct_python; then
    log "WARNING: unit runs Python directly (no xinit)."
    log "On Waveshare 3.5\" this usually means a black screen."
    log "Template: ${PREFIX}/systemd/hwsniff-x11.service"
    log "Not auto-changing your unit (safe-update never rewrites it)."
  fi

  [[ -x "${PREFIX}/.venv/bin/python" ]] || die "missing venv python"
  log "Venv OK ✓"
}

maybe_restart() {
  if [[ "${DO_RESTART}" -ne 1 ]]; then
    log "Checks passed. Service NOT restarted."
    log "When ready:  sudo systemctl restart hwsniff"
    return
  fi
  log "Restarting hwsniff…"
  systemctl reset-failed hwsniff.service 2>/dev/null || true
  systemctl restart hwsniff.service
  sleep 2
  systemctl --no-pager --full status hwsniff.service || true
  if ! systemctl is-active --quiet hwsniff.service; then
    log "hwsniff failed to become active."
    log "Check:  journalctl -u hwsniff -n 80 --no-pager"
    log "Wrapper: sed -n '1,40p' /opt/Sniff/scripts/start-hwsniff-appliance.sh"
    die "service not active after restart (unit/config were NOT rewritten)"
  fi
  log "Service active ✓"
}

main() {
  require_root
  log "Repo:   ${REPO_ROOT}"
  log "Prefix: ${PREFIX}"
  print_unit_summary

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY RUN — no changes"
    [[ -d "${REPO_ROOT}/.git" ]] && git -C "${REPO_ROOT}" status -sb | sed 's/^/[safe-update] /'
    exit 0
  fi

  # Hard refuse dangerous flags if someone wraps this script wrongly.
  for arg in "$@"; do
    case "$arg" in
      --update-unit|--force-unit|--reinstall-deps)
        die "refusing dangerous flag via safe-update: $arg"
        ;;
    esac
  done

  snapshot_protected
  WAS_X11=0
  unit_is_x11_appliance && WAS_X11=1

  git_pull
  sync_code
  verify_and_heal

  if [[ "${WAS_X11}" -eq 1 ]] && ! unit_is_x11_appliance; then
    die "unit was X11 appliance before update but is not after — aborting"
  fi

  print_unit_summary
  maybe_restart
  log "Done. Backup kept at ${BACKUP_DIR}"
}

main "$@"
