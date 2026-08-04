"""Controlled hwsniff.service restart via button chord + systemd Restart=."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Non-zero exit → systemd Restart=on-failure brings the service back.
SERVICE_RESTART_EXIT_CODE = 75

DEFAULT_MARKER_PATH = Path("/run/hwsniff/service_restart")


def marker_path_from_config(config: dict | None) -> Path:
    section = (config or {}).get("service_restart") or {}
    raw = section.get("marker_path") or str(DEFAULT_MARKER_PATH)
    return Path(raw)


def write_restart_marker(path: Path) -> None:
    """One-shot boot marker: next start may resume DIP SWEETP without ERROR3."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n", encoding="utf-8")
        log.info("Service restart marker written path=%s", path)
    except OSError as exc:
        log.warning("Failed to write restart marker %s: %s", path, exc)


def consume_restart_marker(path: Path) -> bool:
    """Return True if marker was present (and remove it)."""
    try:
        if not path.is_file():
            return False
        path.unlink(missing_ok=True)
        log.info("Service restart marker consumed path=%s", path)
        return True
    except OSError as exc:
        log.warning("Failed to consume restart marker %s: %s", path, exc)
        return False
