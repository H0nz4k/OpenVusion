from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient
from .models import ReaderCandidate

log = logging.getLogger(__name__)

ELATEC_VID = 0x09D8
ALIAS_PATH = "/dev/hwsniff-reader"
UART_ALIAS_PATH = "/dev/serial0"


def _score_candidate(item: Any) -> int:
    score = 0
    device = (getattr(item, "device", None) or "").lower()
    desc = (getattr(item, "description", None) or "").upper()
    mfg = (getattr(item, "manufacturer", None) or "").upper()
    product = (getattr(item, "product", None) or "").upper()
    hwid = (getattr(item, "hwid", None) or "").upper()
    vid = getattr(item, "vid", None)
    text = f"{desc} {mfg} {product} {hwid}"

    if vid == ELATEC_VID or "VID:PID=09D8:" in hwid or "VID_09D8" in hwid:
        score += 100
    if "ELATEC" in text or "TWN4" in text:
        score += 40
    if re.search(r"ttyacm|ttyusb", device):
        score += 10
    # Pi GPIO UART aliases (TWN4 Simple Protocol on COM1 @ 9600 8N1)
    if device in ("/dev/serial0", "serial0") or device.endswith("/serial0"):
        score += 35
    elif re.search(r"ttys0|ttyama0|ttyama1", device):
        score += 20
    if device.endswith("hwsniff-reader") or device == ALIAS_PATH:
        score += 30
    return score


def _looks_like_device_path(value: str) -> bool:
    return value.startswith("/dev/") or value.upper().startswith("COM")


def matches_preferred(candidate: ReaderCandidate, preferred: str | None) -> bool:
    """Match USB serial number or device path (incl. resolved symlink)."""
    if not preferred:
        return False
    pref = preferred.strip()
    if not pref:
        return False
    if (candidate.serial_number or "") == pref:
        return True
    if candidate.device == pref:
        return True
    try:
        if Path(candidate.device).resolve() == Path(pref).resolve():
            return True
    except OSError:
        pass
    return False


def enumerate_reader_candidates(
    *,
    list_ports: Callable[[], list[Any]] | None = None,
    preferred_serial: str | None = None,
) -> list[ReaderCandidate]:
    if list_ports is None:
        from serial.tools import list_ports

        ports = list(list_ports.comports())
    else:
        ports = list(list_ports())

    candidates: list[ReaderCandidate] = []
    for item in ports:
        score = _score_candidate(item)
        candidates.append(
            ReaderCandidate(
                device=item.device,
                description=item.description or "",
                hwid=item.hwid or "",
                vid=getattr(item, "vid", None),
                pid=getattr(item, "pid", None),
                manufacturer=getattr(item, "manufacturer", None),
                product=getattr(item, "product", None),
                serial_number=getattr(item, "serial_number", None),
                score=score,
            )
        )

    def _ensure_path_candidate(device: str, description: str, score: int) -> None:
        if not os.path.exists(device):
            return
        if any(c.device == device for c in candidates):
            return
        # Also skip if an existing candidate resolves to the same node.
        try:
            resolved = Path(device).resolve()
            for c in candidates:
                try:
                    if Path(c.device).resolve() == resolved:
                        return
                except OSError:
                    continue
        except OSError:
            pass
        candidates.append(
            ReaderCandidate(
                device=device,
                description=description,
                hwid="",
                score=score,
            )
        )

    # Prefer alias if present on filesystem even if not in comports.
    _ensure_path_candidate(ALIAS_PATH, "hwsniff udev alias", 50)
    _ensure_path_candidate(UART_ALIAS_PATH, "Pi GPIO UART (/dev/serial0)", 45)

    # Explicit preferred device path (e.g. /dev/serial0) always considered.
    if preferred_serial and _looks_like_device_path(preferred_serial):
        _ensure_path_candidate(
            preferred_serial.strip(),
            "preferred serial device",
            80,
        )

    candidates.sort(key=lambda c: (-c.score, c.device))
    return candidates


def handshake_reader(
    device: str,
    *,
    timeout: float = 2.0,
    client_factory: Callable[[str, float], Any] | None = None,
) -> tuple[bool, str | None]:
    """Read-only open + SearchTag probe. Never writes to tag/config."""
    factory = client_factory or (
        lambda port, t: SimpleProtocolClient(port, timeout=t)
    )
    try:
        with factory(device, timeout) as client:
            # SearchTag with no tag present returns None — still proves protocol.
            client.search_tag()
        return True, None
    except (ElatecError, SerialCommunicationError, OSError, ValueError) as exc:
        err = str(exc)
        lower = err.lower()
        if "busy" in lower or "resource temporarily unavailable" in lower or "errno 16" in lower:
            log.warning(
                "Reader port %s busy — stop hwsniff.service before manual UART tests",
                device,
            )
        return False, err


def detect_readers(
    *,
    preferred_serial: str | None = None,
    handshake_timeout: float = 2.0,
    min_score: int = 10,
    list_ports: Callable[[], list[Any]] | None = None,
    client_factory: Callable[[str, float], Any] | None = None,
    verify: bool = True,
) -> list[ReaderCandidate]:
    raw = enumerate_reader_candidates(
        list_ports=list_ports,
        preferred_serial=preferred_serial,
    )
    if preferred_serial:
        raw.sort(
            key=lambda c: (
                0 if matches_preferred(c, preferred_serial) else 1,
                -c.score,
                c.device,
            )
        )
    selected = [c for c in raw if c.score >= min_score] or raw
    if not verify:
        return selected

    verified: list[ReaderCandidate] = []
    for candidate in selected:
        ok, err = handshake_reader(
            candidate.device,
            timeout=handshake_timeout,
            client_factory=client_factory,
        )
        verified.append(
            ReaderCandidate(
                device=candidate.device,
                description=candidate.description,
                hwid=candidate.hwid,
                vid=candidate.vid,
                pid=candidate.pid,
                manufacturer=candidate.manufacturer,
                product=candidate.product,
                serial_number=candidate.serial_number,
                score=candidate.score + (20 if ok else 0),
                verified=ok,
                verify_error=err,
            )
        )
    verified.sort(
        key=lambda c: (
            0 if matches_preferred(c, preferred_serial) else 1,
            -int(c.verified),
            -c.score,
            c.device,
        )
    )
    return verified


def pick_single_reader(candidates: list[ReaderCandidate]) -> ReaderCandidate | None:
    good = [c for c in candidates if c.verified]
    if len(good) == 1:
        return good[0]
    return None


def pick_reader(
    candidates: list[ReaderCandidate],
    *,
    preferred_serial: str | None = None,
    auto_detect: bool = True,
) -> ReaderCandidate | None:
    """Pick preferred verified device, else fall back when auto_detect is True."""
    verified = [c for c in candidates if c.verified]
    if preferred_serial:
        preferred_hits = [
            c for c in verified if matches_preferred(c, preferred_serial)
        ]
        if preferred_hits:
            return preferred_hits[0]
        if not auto_detect:
            log.warning(
                "preferred_serial=%s not verified and auto_detect=false",
                preferred_serial,
            )
            return None
    if len(verified) == 1:
        return verified[0]
    if len(verified) > 1 and preferred_serial:
        # Preferred failed; ambiguous fallback — do not guess.
        log.warning(
            "preferred_serial=%s unavailable; %d other readers verified — not auto-picking",
            preferred_serial,
            len(verified),
        )
        return None
    return None
