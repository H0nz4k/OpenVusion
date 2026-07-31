#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-}"
if [[ -z "${DEST}" ]]; then
  echo "Usage: $0 /media/usb"
  exit 1
fi
SRC_DATA="/var/lib/hwsniff"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${DEST}/hwsniff-export-${STAMP}"
mkdir -p "${OUT}"
cp -a "${SRC_DATA}/captures" "${OUT}/" 2>/dev/null || mkdir -p "${OUT}/captures"
cp -a "${SRC_DATA}/index.csv" "${OUT}/" 2>/dev/null || true
cp -a "${SRC_DATA}/index.jsonl" "${OUT}/" 2>/dev/null || true

MANIFEST="${OUT}/export_manifest.txt"
{
  echo "exported_at=$(date -Is)"
  echo "source=${SRC_DATA}"
  find "${OUT}" -type f | sort
} > "${MANIFEST}"

HASHES="${OUT}/export_sha256.txt"
(
  cd "${OUT}"
  if command -v sha256sum >/dev/null; then
    find . -type f ! -name 'export_sha256.txt' -print0 | sort -z | xargs -0 sha256sum
  fi
) > "${HASHES}"

echo "Export complete: ${OUT}"
echo "Manifest: ${MANIFEST}"
