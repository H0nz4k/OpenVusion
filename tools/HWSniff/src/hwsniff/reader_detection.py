from __future__ import annotations

from typing import Any, Callable

from elatec_uid_tool.field_collector import (
    ReaderCandidate,
    detect_readers,
    pick_reader,
    pick_single_reader,
)


def scan_readers(
    config: dict[str, Any],
    *,
    list_ports: Callable | None = None,
    client_factory: Callable | None = None,
) -> list[ReaderCandidate]:
    reader = config.get("reader") or {}
    return detect_readers(
        preferred_serial=reader.get("preferred_serial"),
        handshake_timeout=float(reader.get("handshake_timeout_seconds", 2)),
        list_ports=list_ports,
        client_factory=client_factory,
        verify=True,
    )


def select_reader(
    candidates: list[ReaderCandidate],
    config: dict[str, Any] | None = None,
) -> ReaderCandidate | None:
    """Prefer configured device path/serial; auto_detect falls back to single match."""
    if config is None:
        return pick_single_reader(candidates)
    reader = config.get("reader") or {}
    return pick_reader(
        candidates,
        preferred_serial=reader.get("preferred_serial"),
        auto_detect=bool(reader.get("auto_detect", True)),
    )
