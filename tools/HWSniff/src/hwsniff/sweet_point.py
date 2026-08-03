"""SweetP samples for HEADLESS: MockSweetPoint + band helpers."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .state import SweetBand, SweetQuality
from .sweetp_bands import SweetPThresholds, band_from_score, thresholds_from_config


@dataclass
class SweetSample:
    score: float | None
    band: SweetBand
    has_tag: bool
    quality: SweetQuality = SweetQuality.NONE  # legacy

    def __post_init__(self) -> None:
        mapping = {
            SweetBand.NONE: SweetQuality.NONE,
            SweetBand.BAD: SweetQuality.LOW,
            SweetBand.BORDERLINE: SweetQuality.LOW,
            SweetBand.USABLE: SweetQuality.MEDIUM,
            SweetBand.GOOD: SweetQuality.HIGH,
        }
        self.quality = mapping[self.band]


class SweetPointService(Protocol):
    def start(self, port: str | None = None) -> None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def get_sample(self) -> SweetSample: ...

    def tick(self, now: float | None = None) -> SweetSample: ...


class MockSweetPoint:
    """Cycle through no-tag / bad / borderline / usable / good for LED tests."""

    def __init__(
        self,
        *,
        period_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        thresholds: SweetPThresholds | None = None,
    ) -> None:
        self.period_seconds = max(0.05, period_seconds)
        self._clock = clock
        self._thresholds = thresholds or SweetPThresholds()
        self._running = False
        self._t0 = 0.0
        self._sample = SweetSample(None, SweetBand.NONE, False)
        self._forced: SweetSample | None = None

    def start(self, port: str | None = None) -> None:
        del port
        self._running = True
        self._t0 = self._clock()
        self.tick()

    def stop(self) -> None:
        self._running = False
        self._forced = None
        self._sample = SweetSample(None, SweetBand.NONE, False)

    def is_running(self) -> bool:
        return self._running

    def get_sample(self) -> SweetSample:
        return self._sample

    def force(self, score: float | None, *, has_tag: bool | None = None) -> None:
        """Test helper — pin a fixed score while running (no hysteresis)."""
        tag = (score is not None) if has_tag is None else has_tag
        band = band_from_score(
            score, has_tag=tag, previous=SweetBand.NONE, thresholds=self._thresholds
        )
        self._forced = SweetSample(score, band, tag)

    def tick(self, now: float | None = None) -> SweetSample:
        if not self._running:
            self._sample = SweetSample(None, SweetBand.NONE, False)
            return self._sample
        if self._forced is not None:
            self._sample = self._forced
            return self._sample
        now = self._clock() if now is None else now
        phase = int((now - self._t0) / self.period_seconds) % 5
        if phase == 0:
            score, tag = None, False
        elif phase == 1:
            score, tag = 25.0, True
        elif phase == 2:
            score, tag = 48.0, True
        elif phase == 3:
            score, tag = 65.0, True
        else:
            wobble = 5.0 * math.sin((now - self._t0) * 3.0)
            score, tag = 85.0 + wobble, True
        band = band_from_score(
            score,
            has_tag=tag,
            previous=self._sample.band,
            thresholds=self._thresholds,
        )
        self._sample = SweetSample(score, band, tag)
        return self._sample


def quality_to_led_levels(quality: SweetQuality) -> dict[str, bool]:
    """Legacy alpha1 mapping (green/orange/red). Prefer band_to_led_patterns."""
    if quality == SweetQuality.HIGH:
        return {"green": True, "orange": False, "red": False}
    if quality == SweetQuality.MEDIUM:
        return {"green": False, "orange": True, "red": False}
    if quality == SweetQuality.LOW:
        return {"green": False, "orange": False, "red": True}
    return {"green": False, "orange": False, "red": False}


def mock_from_config(config: dict, *, clock: Callable[[], float] = time.monotonic) -> MockSweetPoint:
    sweet = config.get("sweetp") or {}
    mock = config.get("mock_sweet_point") or {}
    return MockSweetPoint(
        period_seconds=float(mock.get("period_seconds", 1.0)),
        clock=clock,
        thresholds=thresholds_from_config(sweet),
    )
