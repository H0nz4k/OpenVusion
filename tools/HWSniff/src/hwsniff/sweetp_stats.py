"""Per-cycle SweetP score accumulator → immutable snapshot for summary.json."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SweetPSnapshot:
    """Immutable SweetP stats frozen at READ accept (or empty when unused)."""

    score_at_accept: float | None = None
    band_at_accept: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    sample_count: int = 0
    started_at: str | None = None
    accepted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_at_accept": self.score_at_accept,
            "band_at_accept": self.band_at_accept,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "average": self.average,
            "sample_count": self.sample_count,
            "started_at": self.started_at,
            "accepted_at": self.accepted_at,
        }

    @property
    def empty(self) -> bool:
        return self.sample_count == 0 and self.score_at_accept is None


class SweetPCycleStats:
    """Collect numeric SweetP scores for one positioning/read cycle only."""

    def __init__(self) -> None:
        self._scores: list[float] = []
        self._started_at: str | None = None
        self._frozen: SweetPSnapshot | None = None

    def reset(self) -> None:
        self._scores = []
        self._started_at = None
        self._frozen = None

    @property
    def frozen(self) -> SweetPSnapshot | None:
        return self._frozen

    def add_sample(self, score: float | None, *, has_tag: bool = True) -> None:
        """Record a valid numeric sample; ignore None / no-tag / non-finite."""
        if self._frozen is not None:
            return
        if not has_tag or score is None:
            return
        try:
            value = float(score)
        except (TypeError, ValueError):
            return
        if value != value:  # NaN
            return
        if self._started_at is None:
            self._started_at = _utc_now()
        self._scores.append(value)

    def freeze(
        self,
        *,
        score_at_accept: float | None,
        band_at_accept: str | None,
    ) -> SweetPSnapshot:
        """Create an immutable snapshot; further samples are ignored."""
        if self._frozen is not None:
            return self._frozen
        scores = list(self._scores)
        accept: float | None
        try:
            accept = None if score_at_accept is None else float(score_at_accept)
            if accept is not None and accept != accept:
                accept = None
        except (TypeError, ValueError):
            accept = None
        if scores:
            minimum = min(scores)
            maximum = max(scores)
            average = sum(scores) / len(scores)
            count = len(scores)
        else:
            minimum = maximum = average = None
            count = 0
        self._frozen = SweetPSnapshot(
            score_at_accept=accept,
            band_at_accept=band_at_accept,
            minimum=minimum,
            maximum=maximum,
            average=average,
            sample_count=count,
            started_at=self._started_at,
            accepted_at=_utc_now(),
        )
        return self._frozen

    def empty_snapshot(self) -> SweetPSnapshot:
        return SweetPSnapshot()
