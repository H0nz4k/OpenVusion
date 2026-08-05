"""SweetP samples for HEADLESS: MockSweetPoint + band helpers."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .state import SweetBand, SweetQuality
from .sweetp_bands import SweetPThresholds, band_from_score, thresholds_from_config
from .sweetp_filter import SweetPDualFilter, filter_config_from_sweet


@dataclass
class SweetSample:
    """Live SweetP sample.

    ``score`` is the stable score used for band + READ acceptance.
    ``fast_score`` drives trend overlay only (never READ).
    Scores are read-quality metrics — not RF RSSI.
    """

    score: float | None
    band: SweetBand
    has_tag: bool
    quality: SweetQuality = SweetQuality.NONE  # legacy
    fast_score: float | None = None
    raw_score: float | None = None
    trend_pps: float | None = None
    trend_direction: str = "stable"
    blink_interval_ms: int | None = None
    reader_latency_ms: float | None = None
    seq: int = 0
    t_ms: int = 0

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
    def start(self, port: str | None = None) -> bool: ...

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
        filter_cfg=None,
    ) -> None:
        self.period_seconds = max(0.05, period_seconds)
        self._clock = clock
        self._thresholds = thresholds or SweetPThresholds()
        self._filter = SweetPDualFilter(filter_cfg)
        self._running = False
        self._t0 = 0.0
        self._sample = SweetSample(None, SweetBand.NONE, False)
        self._forced: SweetSample | None = None
        self.reader_error: str | None = None
        self._band = SweetBand.NONE

    def start(self, port: str | None = None) -> bool:
        del port
        self._running = True
        self.reader_error = None
        self._t0 = self._clock()
        self._forced = None
        self._filter.reset()
        self._band = SweetBand.NONE
        self.tick()
        return True

    def stop(self) -> None:
        self._running = False
        self._forced = None
        self.reader_error = None
        self._filter.reset()
        self._sample = SweetSample(None, SweetBand.NONE, False)
        self._band = SweetBand.NONE

    def is_running(self) -> bool:
        return self._running

    def get_sample(self) -> SweetSample:
        return self._sample

    def force(self, score: float | None, *, has_tag: bool | None = None) -> None:
        """Test helper — pin fast+stable to ``score`` (deterministic READ/LED)."""
        tag = (score is not None) if has_tag is None else has_tag
        now = self._clock()
        if not tag or score is None:
            self._filter.reset()
            self._band = SweetBand.NONE
            self._forced = SweetSample(None, SweetBand.NONE, False)
            self._sample = self._forced
            return
        value = float(score)
        # Pin EMAs so legacy tests can set an exact acceptance score.
        self._filter._fast = value
        self._filter._stable = value
        self._filter._has_tag = True
        self._filter._misses = 0
        self._filter._hist.clear()
        self._filter._hist.append((now, value))
        if self._filter._t0 is None:
            self._filter._t0 = now
        self._filter._seq += 1
        band = band_from_score(
            value,
            has_tag=True,
            previous=SweetBand.NONE,
            thresholds=self._thresholds,
        )
        self._band = band
        self._forced = SweetSample(
            score=value,
            band=band,
            has_tag=True,
            fast_score=value,
            raw_score=value,
            trend_pps=None,
            trend_direction="stable",
            blink_interval_ms=None,
            reader_latency_ms=0.0,
            seq=self._filter._seq,
            t_ms=int(max(0.0, (now - self._filter._t0) * 1000.0)),
        )
        self._sample = self._forced

    def push_raw(
        self,
        raw: float | None,
        *,
        has_tag: bool,
        latency_ms: float = 0.0,
        advance: float = 0.0,
    ) -> SweetSample:
        """Test helper: advance clock and feed one raw sample."""
        if advance:
            # Clock may be a Clock() with .advance
            adv = getattr(self._clock, "advance", None)
            if callable(adv):
                adv(advance)
        now = self._clock()
        tick = self._filter.update(raw if has_tag else None, has_tag=has_tag, now=now)
        band = band_from_score(
            tick.stable_score,
            has_tag=tick.has_tag,
            previous=self._band,
            thresholds=self._thresholds,
        )
        self._band = band
        self._sample = SweetSample(
            score=tick.stable_score,
            band=band,
            has_tag=tick.has_tag,
            fast_score=tick.fast_score,
            raw_score=tick.raw_score,
            trend_pps=tick.trend_pps,
            trend_direction=tick.trend_direction,
            blink_interval_ms=tick.blink_interval_ms,
            reader_latency_ms=latency_ms,
            seq=tick.seq,
            t_ms=tick.t_ms,
        )
        self._forced = self._sample
        return self._sample

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
            raw, tag = None, False
        elif phase == 1:
            raw, tag = 25.0, True
        elif phase == 2:
            raw, tag = 48.0, True
        elif phase == 3:
            raw, tag = 65.0, True
        else:
            wobble = 5.0 * math.sin((now - self._t0) * 3.0)
            raw, tag = 85.0 + wobble, True
        tick = self._filter.update(raw, has_tag=tag, now=now)
        band = band_from_score(
            tick.stable_score,
            has_tag=tick.has_tag,
            previous=self._band,
            thresholds=self._thresholds,
        )
        self._band = band
        self._sample = SweetSample(
            score=tick.stable_score,
            band=band,
            has_tag=tick.has_tag,
            fast_score=tick.fast_score,
            raw_score=tick.raw_score,
            trend_pps=tick.trend_pps,
            trend_direction=tick.trend_direction,
            blink_interval_ms=tick.blink_interval_ms,
            seq=tick.seq,
            t_ms=tick.t_ms,
        )
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
        filter_cfg=filter_config_from_sweet(sweet),
    )
