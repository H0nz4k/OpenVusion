"""SweetP score → LED band mapping with hysteresis (HWSniff v2)."""

from __future__ import annotations

from dataclasses import dataclass

from .state import SweetBand


@dataclass(frozen=True)
class SweetPThresholds:
    green_min: float = 75.0
    yellow_min: float = 56.0
    borderline_min: float = 40.0
    borderline_max: float = 55.0
    hysteresis: float = 3.0
    read_minimum: float = 56.0


def thresholds_from_config(sweet: dict) -> SweetPThresholds:
    return SweetPThresholds(
        green_min=float(sweet.get("green_min", 75)),
        yellow_min=float(sweet.get("yellow_min", 56)),
        borderline_min=float(sweet.get("borderline_min", 40)),
        borderline_max=float(sweet.get("borderline_max", 55)),
        hysteresis=float(sweet.get("hysteresis", 3)),
        read_minimum=float(sweet.get("read_minimum", 56)),
    )


def band_from_score(
    score: float | None,
    *,
    has_tag: bool,
    previous: SweetBand = SweetBand.NONE,
    thresholds: SweetPThresholds | None = None,
) -> SweetBand:
    """Map SweetP score to LED band with hysteresis around thresholds."""
    thr = thresholds or SweetPThresholds()
    if not has_tag or score is None:
        return SweetBand.NONE

    h = max(0.0, thr.hysteresis)
    s = float(score)

    # Hysteresis: stay in previous band until crossing threshold ± h.
    if previous == SweetBand.GOOD:
        if s >= thr.green_min - h:
            return SweetBand.GOOD
    if previous == SweetBand.USABLE:
        if thr.yellow_min - h <= s < thr.green_min + h:
            # still not green, and not dropped below yellow
            if s >= thr.yellow_min - h and s < thr.green_min:
                return SweetBand.USABLE
            if s >= thr.green_min:
                return SweetBand.GOOD
    if previous == SweetBand.BORDERLINE:
        if thr.borderline_min - h <= s <= thr.borderline_max + h:
            if s < thr.yellow_min:
                return SweetBand.BORDERLINE
    if previous == SweetBand.BAD:
        if s < thr.borderline_min + h:
            return SweetBand.BAD

    # Absolute mapping (no previous / crossed out of hysteresis).
    if s >= thr.green_min:
        return SweetBand.GOOD
    if s >= thr.yellow_min:
        return SweetBand.USABLE
    if s >= thr.borderline_min:
        return SweetBand.BORDERLINE
    return SweetBand.BAD


def score_allows_read(
    score: float | None,
    *,
    has_tag: bool,
    thresholds: SweetPThresholds | None = None,
) -> bool:
    thr = thresholds or SweetPThresholds()
    if not has_tag or score is None:
        return False
    return float(score) >= thr.read_minimum
