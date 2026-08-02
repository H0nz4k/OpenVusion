from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from elatec_uid_tool.field_collector.reader import (
    ELATEC_VID,
    detect_readers,
    enumerate_reader_candidates,
    handshake_reader,
)


class ReaderSelectionError(RuntimeError):
    """No suitable reader, or ambiguous multi-reader selection."""


@dataclass(frozen=True)
class SelectedReader:
    device: str
    description: str
    hwid: str
    score: int
    verified: bool
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None


def list_all_ports(
    list_ports: Callable[[], list[Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates = enumerate_reader_candidates(list_ports=list_ports)
    return [
        {
            "device": c.device,
            "description": c.description,
            "hwid": c.hwid,
            "vid": c.vid,
            "pid": c.pid,
            "manufacturer": c.manufacturer,
            "product": c.product,
            "score": c.score,
            "verified": c.verified,
        }
        for c in candidates
    ]


def _looks_like_elatec(candidate: Any) -> bool:
    """True for VID/PID/text matches — not merely a successful COM open."""
    if getattr(candidate, "vid", None) == ELATEC_VID:
        return True
    text = " ".join(
        str(x or "")
        for x in (
            getattr(candidate, "description", None),
            getattr(candidate, "manufacturer", None),
            getattr(candidate, "product", None),
            getattr(candidate, "hwid", None),
        )
    ).upper()
    if "VID:PID=09D8:" in text or "VID_09D8" in text:
        return True
    if "ELATEC" in text or "TWN4" in text:
        return True
    # Base score from ElaTool before verify bonus: ELATEC text=+40, VID=+100.
    # After verify, +20 is added — require a strong pre-verify signal.
    score = int(getattr(candidate, "score", 0) or 0)
    verified = bool(getattr(candidate, "verified", False))
    base = score - (20 if verified else 0)
    return base >= 40


def resolve_reader_port(
    *,
    port: str | None = None,
    auto_port: bool = False,
    list_ports: Callable[[], list[Any]] | None = None,
    client_factory: Callable[[str, float], Any] | None = None,
    verify: bool = True,
    min_score: int = 10,
) -> SelectedReader:
    """Resolve a single ELATEC TWN4 COM port for the probe.

    - Explicit ``port`` wins (optional handshake verify).
    - ``auto_port`` requires exactly one verified/high-score ELATEC candidate.
    - Multiple ELATEC readers → error listing them (no random pick).
    - None → error listing all COM ports.
    """
    if port:
        ok, err = True, None
        if verify:
            ok, err = handshake_reader(
                port, timeout=2.0, client_factory=client_factory
            )
        if not ok:
            raise ReaderSelectionError(
                f"Port {port} nelze otevřít / handshake selhal: {err}"
            )
        return SelectedReader(
            device=port,
            description="explicit --port",
            hwid="",
            score=0,
            verified=ok,
        )

    if not auto_port:
        raise ReaderSelectionError(
            "Zadejte --port COMx nebo --auto-port."
        )

    candidates = detect_readers(
        min_score=min_score,
        list_ports=list_ports,
        client_factory=client_factory,
        verify=verify,
    )
    elatec = [c for c in candidates if _looks_like_elatec(c)]
    if verify:
        good = [c for c in elatec if c.verified]
    else:
        good = elatec

    if len(good) == 1:
        c = good[0]
        return SelectedReader(
            device=c.device,
            description=c.description,
            hwid=c.hwid,
            score=c.score,
            verified=c.verified,
            manufacturer=c.manufacturer,
            product=c.product,
            serial_number=c.serial_number,
        )

    if len(good) > 1:
        lines = [
            f"  - {c.device}: {c.description or c.product or '?'} "
            f"(score={c.score}, verified={c.verified})"
            for c in good
        ]
        raise ReaderSelectionError(
            "Nalezeno více ELATEC čteček — vyberte jednu přes --port:\n"
            + "\n".join(lines)
        )

    all_ports = list_all_ports(list_ports=list_ports)
    if not all_ports:
        raise ReaderSelectionError(
            "Nebyl nalezen žádný COM port. Připojte ELATEC TWN4."
        )
    lines = [
        f"  - {p['device']}: {p['description'] or '?'} "
        f"(score={p['score']}, hwid={p['hwid']})"
        for p in all_ports
    ]
    raise ReaderSelectionError(
        "Nebyla nalezena ELATEC TWN4 čtečka. Dostupné COM porty:\n"
        + "\n".join(lines)
        + "\nPoužijte --port COMx pokud víte, který port je čtečka."
    )
