from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


EVENT_TYPES = (
    "capture_started",
    "tag_detected",
    "get_version",
    "session_sample",
    "session_changed",
    "sram_sample",
    "sram_changed",
    "eeprom_sample",
    "eeprom_changed",
    "rf_error",
    "tag_lost",
    "capture_finished",
)


@dataclass
class CaptureEvent:
    """Jedna událost na společné časové ose capture."""

    seq: int
    t_mono_ns: int
    elapsed_us: int
    wall_time: str
    event_type: str
    uid: str | None = None
    rf_operation: str | None = None
    rf_duration_us: int | None = None
    raw_hex: str | None = None
    decoded: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        extra = payload.pop("extra", {}) or {}
        for key, value in extra.items():
            if key not in payload or payload[key] is None:
                payload[key] = value
        # Drop empty optional fields for compact JSONL.
        return {key: value for key, value in payload.items() if value is not None}


def bytes_to_hex(data: bytes | None) -> str | None:
    if data is None:
        return None
    return data.hex(" ").upper()


def safe_ascii_preview(data: bytes, *, placeholder: str = ".") -> str:
    """Bezpečný ASCII náhled; nekontrolovatelné bajty nahradí placeholder."""
    chars: list[str] = []
    for value in data:
        if 32 <= value <= 126:
            chars.append(chr(value))
        else:
            chars.append(placeholder)
    return "".join(chars)
