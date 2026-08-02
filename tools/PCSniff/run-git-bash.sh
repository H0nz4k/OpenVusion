#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/Scripts/python.exe && ! -x .venv/bin/python ]]; then
  echo "Creating virtualenv..."
  python -m venv .venv || py -3 -m venv .venv
  # shellcheck disable=SC1091
  if [[ -f .venv/Scripts/activate ]]; then
    source .venv/Scripts/activate
  else
    source .venv/bin/activate
  fi
  pip install -U pip
  pip install -e "../ElaTool"
  pip install -e ".[dev]"
else
  # shellcheck disable=SC1091
  if [[ -f .venv/Scripts/activate ]]; then
    source .venv/Scripts/activate
  else
    source .venv/bin/activate
  fi
fi

python -m twn4_capture_probe --auto-port "$@"
