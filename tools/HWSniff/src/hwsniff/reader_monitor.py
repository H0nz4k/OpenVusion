"""Non-blocking TWN4 presence monitor for ERROR2 hotplug recovery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class ReaderPresence:
    present: bool
    port: str | None = None
    version: str | None = None
    error: str | None = None


class ReaderMonitor:
    """Poll reader detection on a throttle; never raises to the caller."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        clock: Callable[[], float] = time.monotonic,
        scan_fn: Callable[[dict[str, Any]], list] | None = None,
        select_fn: Callable | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        reader = config.get("reader") or {}
        timing = config.get("timing") or {}
        self.poll_seconds = float(
            reader.get(
                "scan_interval_seconds",
                timing.get("reader_poll_seconds", 1.0),
            )
        )
        self._next = 0.0
        self._last = ReaderPresence(present=False)
        self._scan_fn = scan_fn
        self._select_fn = select_fn

    @property
    def last(self) -> ReaderPresence:
        return self._last

    def tick(self, now: float | None = None, *, force: bool = False) -> ReaderPresence:
        now = self._clock() if now is None else now
        if not force and now < self._next:
            return self._last
        self._next = now + self.poll_seconds
        self._last = self.probe()
        return self._last

    def probe(self) -> ReaderPresence:
        try:
            if self._scan_fn is not None:
                candidates = self._scan_fn(self.config)
            else:
                from .reader_detection import scan_readers

                candidates = scan_readers(self.config)
            if self._select_fn is not None:
                chosen = self._select_fn(candidates)
            else:
                from .reader_detection import select_reader

                chosen = select_reader(candidates)
            if chosen is None:
                return ReaderPresence(present=False, error="no_reader")
            version = None
            # Best-effort version from handshake metadata if present
            version = getattr(chosen, "product", None) or getattr(
                chosen, "description", None
            )
            port = getattr(chosen, "device", None)
            log.debug("Reader present: %s (%s)", port, version)
            return ReaderPresence(present=True, port=port, version=version)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reader probe failed: %s", exc)
            return ReaderPresence(present=False, error=str(exc))
