"""SweetP continuous LED meter (read-quality score → R/Y/G blink rates)."""

from __future__ import annotations

from dataclasses import dataclass

from .patterns import PatternKind


@dataclass(frozen=True)
class SweetLedPlan:
    green: PatternKind
    yellow: PatternKind
    red: PatternKind
    green_period_ms: int | None = None
    yellow_period_ms: int | None = None
    red_period_ms: int | None = None
    pulse_ms: int = 120


def _lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


def _period(a: float, b: float, t: float) -> int:
    return max(120, int(round(_lerp(a, b, t))))


def plan_sweetp_leds(
    score: float | None,
    *,
    has_tag: bool,
    green_min: float = 75.0,
    yellow_min: float = 56.0,
    borderline_min: float = 40.0,
) -> SweetLedPlan:
    """Map quality score to LED plan.

    - no tag / no score: fast red blink
    - weak: slower red (+ yellow enters near borderline)
    - usable: no red; yellow slower + green faster as score rises
    - good: solid green only
    """
    if not has_tag or score is None:
        return SweetLedPlan(
            green=PatternKind.OFF,
            yellow=PatternKind.OFF,
            red=PatternKind.PERIODIC_PULSE,
            red_period_ms=180,
            pulse_ms=90,
        )

    s = float(score)
    g_min = float(green_min)
    y_min = float(yellow_min)
    b_min = float(borderline_min)

    # Best: solid green.
    if s >= g_min:
        return SweetLedPlan(
            green=PatternKind.ON,
            yellow=PatternKind.OFF,
            red=PatternKind.OFF,
        )

    # Usable → approaching green: yellow slows, green speeds up.
    if s >= y_min:
        t = (s - y_min) / max(1e-6, g_min - y_min)
        return SweetLedPlan(
            green=PatternKind.PERIODIC_PULSE,
            yellow=PatternKind.PERIODIC_PULSE,
            red=PatternKind.OFF,
            green_period_ms=_period(850, 260, t),
            yellow_period_ms=_period(420, 1100, t),
            pulse_ms=140,
        )

    # Borderline: red slows, yellow appears.
    if s >= b_min:
        t = (s - b_min) / max(1e-6, y_min - b_min)
        return SweetLedPlan(
            green=PatternKind.OFF,
            yellow=PatternKind.PERIODIC_PULSE,
            red=PatternKind.PERIODIC_PULSE,
            yellow_period_ms=_period(700, 500, t),
            red_period_ms=_period(420, 750, t),
            pulse_ms=130,
        )

    # Weak / bad: fast→slower red; yellow creeps in near the top of the band.
    t = s / max(1e-6, b_min)
    yellow = PatternKind.OFF
    yellow_period = None
    if t >= 0.55:
        yellow = PatternKind.PERIODIC_PULSE
        yellow_period = _period(900, 650, (t - 0.55) / 0.45)
    return SweetLedPlan(
        green=PatternKind.OFF,
        yellow=yellow,
        red=PatternKind.PERIODIC_PULSE,
        yellow_period_ms=yellow_period,
        red_period_ms=_period(160, 400, t),
        pulse_ms=100,
    )
