from __future__ import annotations

import os
import re
from typing import Any, Callable

from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient
from .models import ReaderCandidate

ELATEC_VID = 0x09D8
ALIAS_PATH = "/dev/hwsniff-reader"


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
    if device.endswith("hwsniff-reader") or device == ALIAS_PATH:
        score += 30
    return score


def enumerate_reader_candidates(
    *,
    list_ports: Callable[[], list[Any]] | None = None,
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
    # Prefer alias if present on filesystem even if not in comports.
    if os.path.exists(ALIAS_PATH) and not any(c.device == ALIAS_PATH for c in candidates):
        candidates.append(
            ReaderCandidate(
                device=ALIAS_PATH,
                description="hwsniff udev alias",
                hwid="",
                score=50,
            )
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
        return False, str(exc)


def detect_readers(
    *,
    preferred_serial: str | None = None,
    handshake_timeout: float = 2.0,
    min_score: int = 10,
    list_ports: Callable[[], list[Any]] | None = None,
    client_factory: Callable[[str, float], Any] | None = None,
    verify: bool = True,
) -> list[ReaderCandidate]:
    raw = enumerate_reader_candidates(list_ports=list_ports)
    if preferred_serial:
        raw.sort(
            key=lambda c: (
                0 if (c.serial_number or "") == preferred_serial else 1,
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
    verified.sort(key=lambda c: (-int(c.verified), -c.score, c.device))
    return verified


def pick_single_reader(candidates: list[ReaderCandidate]) -> ReaderCandidate | None:
    good = [c for c in candidates if c.verified]
    if len(good) == 1:
        return good[0]
    return None
