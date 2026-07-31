#!/usr/bin/env bash
set -euo pipefail
sudo systemctl start hwsniff.service
sudo systemctl status hwsniff.service --no-pager
