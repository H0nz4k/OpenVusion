"""Lightweight WLAN status monitor (non-blocking poll)."""

from __future__ import annotations

import logging
import socket
import subprocess
from pathlib import Path
from typing import Callable

from .state import WlanStatus

log = logging.getLogger(__name__)


def _sysfs_iface(interface: str) -> Path:
    return Path("/sys/class/net") / interface


def probe_wlan(
    interface: str = "wlan0",
    *,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> tuple[WlanStatus, str | None]:
    """Return (status, ip_or_none). Never raises for missing iface."""
    run = run or subprocess.run
    base = _sysfs_iface(interface)
    try:
        if not base.exists():
            return WlanStatus.OFFLINE, None
        oper = (base / "operstate").read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        log.debug("wlan sysfs error: %s", exc)
        return WlanStatus.OFFLINE, None

    if oper in {"down", "unknown", ""}:
        return WlanStatus.OFFLINE, None

    ip = _ipv4_from_ip_cmd(interface, run=run)
    if ip is None:
        ip = _ipv4_from_hostname()
        # hostname may not be interface-specific; only use if oper is up
        if oper != "up":
            ip = None

    if ip:
        return WlanStatus.CONNECTED, ip

    # Interface present / up-ish but no address yet
    if oper in {"up", "dormant", "lowerlayerdown"}:
        return WlanStatus.CONNECTING, None
    return WlanStatus.OFFLINE, None


def _ipv4_from_ip_cmd(
    interface: str,
    *,
    run: Callable[..., subprocess.CompletedProcess],
) -> str | None:
    try:
        proc = run(
            ["ip", "-4", "-o", "addr", "show", "dev", interface],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    # example: "2: wlan0    inet 192.168.1.50/24 ..."
    for token in proc.stdout.split():
        if "/" in token and token[0].isdigit():
            return token.split("/", 1)[0]
    return None


def _ipv4_from_hostname() -> str | None:
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in infos:
            addr = info[4][0]
            if not addr.startswith("127."):
                return addr
    except OSError:
        return None
    return None


class NetworkMonitor:
    def __init__(
        self,
        interface: str = "wlan0",
        poll_seconds: float = 3.0,
        *,
        clock=None,
        probe=probe_wlan,
    ) -> None:
        import time

        self.interface = interface
        self.poll_seconds = poll_seconds
        self._clock = clock or time.monotonic
        self._probe = probe
        self.status = WlanStatus.OFFLINE
        self.ip: str | None = None
        self._next = 0.0

    def tick(self, now: float | None = None) -> bool:
        """Refresh if due. Returns True when status/ip changed."""
        now = self._clock() if now is None else now
        if now < self._next:
            return False
        self._next = now + self.poll_seconds
        status, ip = self._probe(self.interface)
        changed = status != self.status or ip != self.ip
        self.status = status
        self.ip = ip
        if changed:
            log.info("WLAN %s ip=%s", status.value, ip)
        return changed
