"""Fast/stable SweetP filters and trend (read-quality score, not RF RSSI)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque


@dataclass(frozen=True)
class SweetPFilterConfig:
    fast_alpha: float = 0.60
    stable_alpha: float = 0.20
    trend_window_samples: int = 3
    trend_deadband_points_per_second: float = 8.0
    trend_strong_points_per_second: float = 40.0
    trend_min_blink_interval_ms: int = 200
    trend_max_blink_interval_ms: int = 1000
    trend_pulse_ms: int = 80
    no_tag_confirm_samples: int = 2
    max_trace_samples: int = 2000

    def to_dict(self) -> dict[str, Any]:
        return {
            "fast_alpha": self.fast_alpha,
            "stable_alpha": self.stable_alpha,
            "trend_window_samples": self.trend_window_samples,
            "trend_deadband_points_per_second": self.trend_deadband_points_per_second,
            "trend_strong_points_per_second": self.trend_strong_points_per_second,
            "trend_min_blink_interval_ms": self.trend_min_blink_interval_ms,
            "trend_max_blink_interval_ms": self.trend_max_blink_interval_ms,
            "trend_pulse_ms": self.trend_pulse_ms,
            "no_tag_confirm_samples": self.no_tag_confirm_samples,
            "max_trace_samples": self.max_trace_samples,
        }


def filter_config_from_sweet(sweet: dict[str, Any] | None) -> SweetPFilterConfig:
    s = sweet or {}
    return SweetPFilterConfig(
        fast_alpha=_clamp_alpha(float(s.get("fast_alpha", 0.60))),
        stable_alpha=_clamp_alpha(float(s.get("stable_alpha", 0.20))),
        trend_window_samples=max(2, int(s.get("trend_window_samples", 3))),
        trend_deadband_points_per_second=max(
            0.0, float(s.get("trend_deadband_points_per_second", 8.0))
        ),
        trend_strong_points_per_second=max(
            1.0, float(s.get("trend_strong_points_per_second", 40.0))
        ),
        trend_min_blink_interval_ms=max(
            50, int(s.get("trend_min_blink_interval_ms", 200))
        ),
        trend_max_blink_interval_ms=max(
            100, int(s.get("trend_max_blink_interval_ms", 1000))
        ),
        trend_pulse_ms=max(20, int(s.get("trend_pulse_ms", 80))),
        no_tag_confirm_samples=max(1, int(s.get("no_tag_confirm_samples", 2))),
        max_trace_samples=max(50, int(s.get("max_trace_samples", 2000))),
    )


def _clamp_alpha(value: float) -> float:
    return max(0.01, min(1.0, value))


@dataclass(frozen=True)
class FilterTick:
    raw_score: float | None
    fast_score: float | None
    stable_score: float | None
    trend_pps: float | None
    trend_direction: str  # improving | worsening | stable
    blink_interval_ms: int | None
    has_tag: bool
    seq: int
    t_ms: int


class SweetPDualFilter:
    """EMA fast/stable scores + slope trend for LED overlay (not READ gate)."""

    def __init__(self, cfg: SweetPFilterConfig | None = None) -> None:
        self.cfg = cfg or SweetPFilterConfig()
        self.reset()

    def reset(self) -> None:
        self._fast: float | None = None
        self._stable: float | None = None
        self._hist: Deque[tuple[float, float]] = deque(
            maxlen=max(2, self.cfg.trend_window_samples)
        )
        self._misses = 0
        self._seq = 0
        self._t0: float | None = None
        self._has_tag = False

    @property
    def fast_score(self) -> float | None:
        return self._fast

    @property
    def stable_score(self) -> float | None:
        return self._stable

    def update(
        self,
        raw_score: float | None,
        *,
        has_tag: bool,
        now: float,
    ) -> FilterTick:
        if self._t0 is None:
            self._t0 = now
        t_ms = int(max(0.0, (now - self._t0) * 1000.0))

        if not has_tag or raw_score is None:
            self._misses += 1
            if self._misses >= self.cfg.no_tag_confirm_samples:
                self._fast = None
                self._stable = None
                self._hist.clear()
                self._has_tag = False
            self._seq += 1
            return FilterTick(
                raw_score=None,
                fast_score=self._fast if self._has_tag else None,
                stable_score=self._stable if self._has_tag else None,
                trend_pps=None,
                trend_direction="stable",
                blink_interval_ms=None,
                has_tag=False,
                seq=self._seq,
                t_ms=t_ms,
            )

        self._misses = 0
        self._has_tag = True
        value = float(raw_score)
        if self._fast is None:
            self._fast = value
            self._stable = value
        else:
            a_f = self.cfg.fast_alpha
            a_s = self.cfg.stable_alpha
            self._fast = a_f * value + (1.0 - a_f) * self._fast
            assert self._stable is not None
            self._stable = a_s * value + (1.0 - a_s) * self._stable

        self._hist.append((now, self._fast))
        trend_pps, direction, blink_ms = self._compute_trend()
        self._seq += 1
        return FilterTick(
            raw_score=value,
            fast_score=self._fast,
            stable_score=self._stable,
            trend_pps=trend_pps,
            trend_direction=direction,
            blink_interval_ms=blink_ms,
            has_tag=True,
            seq=self._seq,
            t_ms=t_ms,
        )

    def _compute_trend(self) -> tuple[float | None, str, int | None]:
        if len(self._hist) < 2:
            return None, "stable", None
        t0, s0 = self._hist[0]
        t1, s1 = self._hist[-1]
        dt = t1 - t0
        if dt <= 1e-6:
            return None, "stable", None
        # Clamp one-shot spikes to strong range before slope.
        delta = max(-self.cfg.trend_strong_points_per_second * dt * 1.5, min(
            self.cfg.trend_strong_points_per_second * dt * 1.5, s1 - s0
        ))
        pps = delta / dt
        dead = self.cfg.trend_deadband_points_per_second
        if abs(pps) < dead:
            return pps, "stable", None
        direction = "improving" if pps > 0 else "worsening"
        strong = self.cfg.trend_strong_points_per_second
        # Map |pps| from dead..strong → max_blink..min_blink
        intensity = min(1.0, (abs(pps) - dead) / max(1e-6, strong - dead))
        lo = float(self.cfg.trend_min_blink_interval_ms)
        hi = float(self.cfg.trend_max_blink_interval_ms)
        if hi < lo:
            hi = lo
        blink = int(round(hi - intensity * (hi - lo)))
        return pps, direction, blink
