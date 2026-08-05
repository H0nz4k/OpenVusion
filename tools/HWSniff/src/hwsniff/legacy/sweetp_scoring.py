"""SweetP live position-quality scoring (communication quality, not RF RSSI)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Deque


class SweetPTrend(str, Enum):
    IMPROVING = "improving"
    WORSENING = "worsening"
    STABLE = "stable"


@dataclass(frozen=True)
class SweetPSample:
    success: bool
    uid: str | None
    latency_ms: float
    monotonic_ts: float


@dataclass
class SweetPLiveSnapshot:
    current_quality: float
    best_quality: float
    trend: SweetPTrend
    window_successes: int
    window_total: int
    total_successes: int
    total_failures: int
    dominant_uid: str | None
    uid_consistency: float
    average_latency_ms: float | None
    stable_duration_ms: int
    enough_samples: bool
    position_ok: bool
    latency_available: bool


@dataclass
class ScoringConfig:
    window_size: int = 20
    short_window_size: int = 5
    trend_threshold: float = 5.0
    trend_hold_ms: int = 800
    good_quality_threshold: float = 85.0
    poor_quality_threshold: float = 50.0
    good_hold_ms: int = 3000
    min_samples_for_trend: int = 5
    min_samples_for_ok: int = 8
    latency_good_ms: float = 80.0
    latency_bad_ms: float = 600.0
    weight_success: float = 0.60
    weight_latency: float = 0.25
    weight_uid_consistency: float = 0.15
    use_latency: bool = True


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def latency_score(latency_ms: float, good_ms: float, bad_ms: float) -> float:
    """Map latency to 0..1 (1 = fast)."""
    if bad_ms <= good_ms:
        return 1.0 if latency_ms <= good_ms else 0.0
    if latency_ms <= good_ms:
        return 1.0
    if latency_ms >= bad_ms:
        return 0.0
    return 1.0 - (latency_ms - good_ms) / (bad_ms - good_ms)


def single_sample_quality(sample: SweetPSample, cfg: ScoringConfig) -> float | None:
    """Instant read-quality for one probe (not RF RSSI). None if unsuccessful."""
    if not sample.success or not sample.uid:
        return None
    quality, *_rest = quality_from_window([sample], cfg)
    return quality


def quality_from_window(
    samples: list[SweetPSample],
    cfg: ScoringConfig,
) -> tuple[float, float, float, str | None, float | None]:
    """Return (quality, success_rate, uid_consistency, dominant_uid, avg_latency)."""
    if not samples:
        return 0.0, 0.0, 0.0, None, None

    successes = [s for s in samples if s.success]
    success_rate = len(successes) / len(samples)

    dominant_uid: str | None = None
    uid_consistency = 0.0
    if successes:
        counts: dict[str, int] = {}
        for sample in successes:
            if sample.uid:
                counts[sample.uid] = counts.get(sample.uid, 0) + 1
        if counts:
            dominant_uid = max(counts, key=counts.get)
            uid_consistency = counts[dominant_uid] / len(successes)

    avg_latency: float | None = None
    lat_component = 0.0
    if cfg.use_latency:
        latencies = [s.latency_ms for s in samples]
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            lat_component = sum(
                latency_score(v, cfg.latency_good_ms, cfg.latency_bad_ms)
                for v in latencies
            ) / len(latencies)

    if cfg.use_latency:
        w_s, w_l, w_u = cfg.weight_success, cfg.weight_latency, cfg.weight_uid_consistency
        total_w = w_s + w_l + w_u
    else:
        w_s, w_l, w_u = 0.80, 0.0, 0.20
        total_w = 1.0

    quality = 100.0 * (
        (w_s * success_rate) + (w_l * lat_component) + (w_u * uid_consistency)
    ) / total_w
    return _clamp(quality), success_rate, uid_consistency, dominant_uid, avg_latency


class SweetPScorer:
    """Maintains rolling windows and derives live quality / trend / POSITION OK."""

    def __init__(
        self,
        cfg: ScoringConfig,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.cfg = cfg
        self._clock = clock or (lambda: __import__("time").monotonic())
        self._samples: Deque[SweetPSample] = deque(maxlen=max(1, cfg.window_size))
        self.best_quality = 0.0
        self.total_successes = 0
        self.total_failures = 0
        self._trend = SweetPTrend.STABLE
        self._trend_since = self._clock()
        self._good_since: float | None = None
        self._position_ok = False
        self._last_quality = 0.0
        self._quality_history: Deque[float] = deque(maxlen=max(1, cfg.window_size))

    def reset(self) -> None:
        self._samples.clear()
        self._quality_history.clear()
        self.best_quality = 0.0
        self.total_successes = 0
        self.total_failures = 0
        self._trend = SweetPTrend.STABLE
        self._trend_since = self._clock()
        self._good_since = None
        self._position_ok = False
        self._last_quality = 0.0

    def recent_quality(self, window: int | None = None) -> float | None:
        """Quality over the last N samples (default short_window_size).

        Used by headless live LEDs so intermittent SearchTag misses move the
        meter; a single always-successful probe always scores ~81 with UART
        latency alone and is useless for positioning.
        """
        if not self._samples:
            return None
        n = max(1, int(window if window is not None else self.cfg.short_window_size))
        samples = list(self._samples)[-n:]
        quality, *_rest = quality_from_window(samples, self.cfg)
        return quality

    def add_sample(self, sample: SweetPSample) -> SweetPLiveSnapshot:
        if sample.success:
            self.total_successes += 1
        else:
            self.total_failures += 1
        self._samples.append(sample)

        quality, _sr, uid_c, dominant, avg_lat = quality_from_window(
            list(self._samples), self.cfg
        )
        self._quality_history.append(quality)
        self.best_quality = max(self.best_quality, quality)
        self._update_trend(quality)
        self._update_position_ok(quality, uid_c)
        self._last_quality = quality

        enough = len(self._samples) >= min(
            self.cfg.min_samples_for_ok, self.cfg.window_size
        )
        stable_ms = 0
        if self._good_since is not None:
            stable_ms = int(max(0.0, (self._clock() - self._good_since) * 1000))

        return SweetPLiveSnapshot(
            current_quality=quality,
            best_quality=self.best_quality,
            trend=self._trend,
            window_successes=sum(1 for s in self._samples if s.success),
            window_total=len(self._samples),
            total_successes=self.total_successes,
            total_failures=self.total_failures,
            dominant_uid=dominant,
            uid_consistency=uid_c,
            average_latency_ms=avg_lat,
            stable_duration_ms=stable_ms,
            enough_samples=enough,
            position_ok=self._position_ok,
            latency_available=self.cfg.use_latency and avg_lat is not None,
        )

    def snapshot(self) -> SweetPLiveSnapshot:
        quality, _sr, uid_c, dominant, avg_lat = quality_from_window(
            list(self._samples), self.cfg
        )
        enough = len(self._samples) >= min(
            self.cfg.min_samples_for_ok, self.cfg.window_size
        )
        stable_ms = 0
        if self._good_since is not None:
            stable_ms = int(max(0.0, (self._clock() - self._good_since) * 1000))
        return SweetPLiveSnapshot(
            current_quality=quality if self._samples else 0.0,
            best_quality=self.best_quality,
            trend=self._trend,
            window_successes=sum(1 for s in self._samples if s.success),
            window_total=len(self._samples),
            total_successes=self.total_successes,
            total_failures=self.total_failures,
            dominant_uid=dominant,
            uid_consistency=uid_c,
            average_latency_ms=avg_lat,
            stable_duration_ms=stable_ms,
            enough_samples=enough,
            position_ok=self._position_ok,
            latency_available=self.cfg.use_latency and avg_lat is not None,
        )

    def _update_trend(self, quality: float) -> None:
        cfg = self.cfg
        if len(self._quality_history) < cfg.min_samples_for_trend:
            self._trend = SweetPTrend.STABLE
            return

        short_n = min(cfg.short_window_size, len(self._quality_history))
        short_vals = list(self._quality_history)[-short_n:]
        short_avg = sum(short_vals) / len(short_vals)

        older = list(self._quality_history)[:-short_n]
        ref = sum(older) / len(older) if older else self._last_quality
        delta = short_avg - ref

        desired = SweetPTrend.STABLE
        if delta >= cfg.trend_threshold:
            desired = SweetPTrend.IMPROVING
        elif delta <= -cfg.trend_threshold:
            desired = SweetPTrend.WORSENING

        now = self._clock()
        if desired != self._trend and (now - self._trend_since) * 1000.0 >= cfg.trend_hold_ms:
            self._trend = desired
            self._trend_since = now

    def _update_position_ok(self, quality: float, uid_consistency: float) -> None:
        cfg = self.cfg
        now = self._clock()
        enough = len(self._samples) >= cfg.min_samples_for_ok
        good = (
            enough
            and quality >= cfg.good_quality_threshold
            and uid_consistency >= 0.95
        )
        if good:
            if self._good_since is None:
                self._good_since = now
            self._position_ok = (now - self._good_since) * 1000.0 >= cfg.good_hold_ms
            return
        self._good_since = None
        self._position_ok = False
