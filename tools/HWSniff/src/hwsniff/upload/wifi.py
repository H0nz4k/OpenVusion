"""WiFi readiness: interface up + IPv4 + default route (not DNS-only)."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Callable

from ..network import probe_wlan
from ..state import WlanStatus

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WifiCheck:
    ready: bool
    status: WlanStatus
    ip: str | None
    has_default_route: bool
    detail: str


def check_wifi_ready(
    interface: str = "wlan0",
    *,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
    probe=probe_wlan,
) -> WifiCheck:
    run = run or subprocess.run
    status, ip = probe(interface, run=run)
    if status != WlanStatus.CONNECTED or not ip:
        return WifiCheck(
            ready=False,
            status=status,
            ip=ip,
            has_default_route=False,
            detail="no_wifi" if status == WlanStatus.OFFLINE else "no_ip",
        )
    has_route = _has_default_route(interface, run=run)
    if not has_route:
        return WifiCheck(
            ready=False,
            status=status,
            ip=ip,
            has_default_route=False,
            detail="no_default_route",
        )
    return WifiCheck(
        ready=True,
        status=status,
        ip=ip,
        has_default_route=True,
        detail="ok",
    )


def _has_default_route(
    interface: str,
    *,
    run: Callable[..., subprocess.CompletedProcess],
) -> bool:
    try:
        proc = run(
            ["ip", "-4", "route", "show", "default"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0 or not proc.stdout:
        return False
    text = proc.stdout
    # Prefer route via our interface; accept any default as usable path.
    if f"dev {interface}" in text:
        return True
    return "default" in text
