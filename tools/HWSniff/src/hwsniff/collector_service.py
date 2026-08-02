"""Collector interface for headless HWSniff + alpha1 MockCollector.

Alpha2 will replace MockCollector with the shared ElaTool/PCSniff engine
without changing the GPIO state machine.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .state import CollectorOutcome, DipMode

log = logging.getLogger(__name__)


@dataclass
class CollectorProgress:
    phase: str = ""
    message: str = ""


@dataclass
class CollectorResult:
    outcome: CollectorOutcome
    message: str = ""
    mode: DipMode | None = None


class CollectorService(Protocol):
    def start(self, mode: DipMode) -> None: ...

    def request_stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def get_progress(self) -> CollectorProgress: ...

    def get_result(self) -> CollectorResult | None: ...

    def tick(self, now: float | None = None) -> None: ...


class MockCollector:
    """Simulated capture for alpha1 — tick-driven, no worker thread."""

    def __init__(
        self,
        *,
        work_seconds: float = 2.0,
        save_seconds: float = 0.3,
        outcome: CollectorOutcome | str = CollectorOutcome.SUCCESS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.work_seconds = work_seconds
        self.save_seconds = save_seconds
        if isinstance(outcome, str):
            outcome = CollectorOutcome(outcome)
        self.default_outcome = outcome
        self._clock = clock
        self._running = False
        self._stop = False
        self._progress = CollectorProgress()
        self._result: CollectorResult | None = None
        self._mode: DipMode | None = None
        self._t0 = 0.0
        self.on_phase: Callable[[str], None] | None = None
        self._phase = ""

    def start(self, mode: DipMode) -> None:
        if self._running:
            return
        self._stop = False
        self._result = None
        self._mode = mode
        self._running = True
        self._t0 = self._clock()
        self._set_phase("reading")

    def request_stop(self) -> None:
        self._stop = True

    def is_running(self) -> bool:
        return self._running

    def get_progress(self) -> CollectorProgress:
        return self._progress

    def get_result(self) -> CollectorResult | None:
        return self._result

    def tick(self, now: float | None = None) -> None:
        if not self._running:
            return
        now = self._clock() if now is None else now
        if self._stop:
            self._finish(CollectorOutcome.CANCELLED, "stopped")
            return
        elapsed = now - self._t0
        if elapsed < self.work_seconds:
            return
        if self._phase != "saving":
            self._set_phase("saving")
        if elapsed < self.work_seconds + self.save_seconds:
            return
        self._finish(self.default_outcome, "mock complete")

    def _set_phase(self, phase: str) -> None:
        self._phase = phase
        self._progress = CollectorProgress(phase=phase, message=phase)
        if self.on_phase:
            try:
                self.on_phase(phase)
            except Exception:  # noqa: BLE001
                log.exception("on_phase callback failed")

    def _finish(self, outcome: CollectorOutcome, message: str) -> None:
        self._result = CollectorResult(
            outcome=outcome, message=message, mode=self._mode
        )
        self._running = False
