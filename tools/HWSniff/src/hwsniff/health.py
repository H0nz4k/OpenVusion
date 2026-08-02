"""Basic alpha1 health checks (GPIO + optional paths)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class HealthReport:
    ok: bool
    errors: list[str]
    details: dict[str, Any]


def run_health_checks(
    *,
    gpio_ok: bool = True,
    data_root: str | Path | None = None,
    require_wlan: bool = False,
    wlan_connected: bool = False,
) -> HealthReport:
    errors: list[str] = []
    details: dict[str, Any] = {}
    if not gpio_ok:
        errors.append("gpio_init_failed")
    if data_root is not None:
        root = Path(data_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".hwsniff_health_probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            details["data_root_writable"] = True
        except OSError as exc:
            errors.append(f"data_root_not_writable:{exc}")
            details["data_root_writable"] = False
    if require_wlan and not wlan_connected:
        errors.append("wlan_required")
    ok = not errors
    if not ok:
        log.warning("Health check failed: %s", errors)
    return HealthReport(ok=ok, errors=errors, details=details)
