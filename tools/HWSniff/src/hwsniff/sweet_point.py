"""Alpha1 MockSweetPoint — simulated quality score for LED mapping."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from .state import SweetQuality


@dataclass
class SweetSample:
    score: float | None
    quality: SweetQuality
    has_tag: bool


class MockSweetPoint:
    """Cycle through no-tag / low / medium / high for hardware validation."""

    def __init__(
        self,
        *,
        period_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.period_seconds = max(0.05, period_seconds)
        self._clock = clock
        self._running = False
        self._t0 = 0.0
        self._sample = SweetSample(None, SweetQuality.NONE, False)

    def start(self) -> None:
        self._running = True
        self._t0 = self._clock()
        self.tick()

    def stop(self) -> None:
        self._running = False
        self._sample = SweetSample(None, SweetQuality.NONE, False)

    def is_running(self) -> bool:
        return self._running

    def get_sample(self) -> SweetSample:
        return self._sample

    def tick(self, now: float | None = None) -> SweetSample:
        if not self._running:
            self._sample = SweetSample(None, SweetQuality.NONE, False)
            return self._sample
        now = self._clock() if now is None else now
        # 4 phases over 4*period: none → low → medium → high → …
        phase = int((now - self._t0) / self.period_seconds) % 4
        if phase == 0:
            self._sample = SweetSample(None, SweetQuality.NONE, False)
        elif phase == 1:
            self._sample = SweetSample(25.0, SweetQuality.LOW, True)
        elif phase == 2:
            self._sample = SweetSample(55.0, SweetQuality.MEDIUM, True)
        else:
            # slight variation within high band
            wobble = 5.0 * math.sin((now - self._t0) * 3.0)
            self._sample = SweetSample(85.0 + wobble, SweetQuality.HIGH, True)
        return self._sample


def quality_to_led_levels(quality: SweetQuality) -> dict[str, bool]:
    """GREEN=high, ORANGE=medium, RED=low; no tag → all off."""
    if quality == SweetQuality.HIGH:
        return {"green": True, "orange": False, "red": False}
    if quality == SweetQuality.MEDIUM:
        return {"green": False, "orange": True, "red": False}
    if quality == SweetQuality.LOW:
        return {"green": False, "orange": False, "red": True}
    return {"green": False, "orange": False, "red": False}
