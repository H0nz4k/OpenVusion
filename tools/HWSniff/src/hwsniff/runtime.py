"""Writable runtime directory for lgpio/gpiozero notify pipes.

lgpio creates ``.lgd-nfy*`` files in the process cwd. Service and CLI must
never rely on ``/opt/Sniff`` being writable by user ``hwsniff``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_RUNTIME_DIR = "/var/lib/hwsniff"


def resolve_runtime_dir(config: dict[str, Any] | None = None) -> Path:
    cfg = config or {}
    candidates = [
        cfg.get("data_root"),
        os.environ.get("HWSNIFF_RUNTIME_DIR"),
        DEFAULT_RUNTIME_DIR,
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".hwsniff_runtime_probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except OSError as exc:
            log.debug("runtime dir not usable %s: %s", path, exc)
    # Last resort for unit tests / non-Pi hosts
    return Path(tempfile.mkdtemp(prefix="hwsniff-runtime-"))


def ensure_runtime_cwd(config: dict[str, Any] | None = None) -> Path:
    """Create/verify runtime dir and chdir into it before GPIO init."""
    runtime = resolve_runtime_dir(config)
    try:
        os.chdir(runtime)
    except OSError as exc:
        log.warning("chdir(%s) failed: %s", runtime, exc)
        return runtime
    # Help libraries that honour HOME for caches/pipes.
    os.environ.setdefault("HOME", str(runtime))
    log.debug("runtime cwd=%s", runtime)
    return runtime
