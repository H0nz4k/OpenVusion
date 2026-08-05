"""Per-cycle SweetP score accumulator + immutable snapshot / trace."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    filter_config: dict[str, Any] = field(default_factory=dict)
    trace_lines: tuple[str, ...] = ()

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
            "filter_config": dict(self.filter_config),
            # Not RSSI — read-quality score derived from Simple Protocol probes.
            "score_kind": "read_quality",
        }

    def trace_jsonl(self) -> str:
        if not self.trace_lines:
            return ""
        return "\n".join(self.trace_lines) + "\n"

    @property
    def empty(self) -> bool:
        return self.sample_count == 0 and self.score_at_accept is None


class SweetPCycleStats:
    """Collect numeric SweetP scores + diagnostic trace for one cycle only."""

    def __init__(self, *, max_trace_samples: int = 2000) -> None:
        self.max_trace_samples = max_trace_samples
        self._scores: list[float] = []
        self._trace: list[dict[str, Any]] = []
        self._started_at: str | None = None
        self._frozen: SweetPSnapshot | None = None
        self._filter_config: dict[str, Any] = {}

    def reset(self, *, filter_config: dict[str, Any] | None = None) -> None:
        self._scores = []
        self._trace = []
        self._started_at = None
        self._frozen = None
        if filter_config is not None:
            self._filter_config = dict(filter_config)

    def set_filter_config(self, cfg: dict[str, Any]) -> None:
        if self._frozen is None:
            self._filter_config = dict(cfg)

    @property
    def frozen(self) -> SweetPSnapshot | None:
        return self._frozen

    def add_sample(
        self,
        score: float | None,
        *,
        has_tag: bool = True,
        trace_row: dict[str, Any] | None = None,
    ) -> None:
        """Record a valid numeric sample; ignore None / no-tag / non-finite."""
        if self._frozen is not None:
            return
        if trace_row is not None and len(self._trace) < self.max_trace_samples:
            self._trace.append(dict(trace_row))
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

        # Mark the accept sample in a frozen copy of the trace.
        lines: list[str] = []
        for row in self._trace:
            item = dict(row)
            if accept is not None and item.get("stable_score") is not None:
                try:
                    if abs(float(item["stable_score"]) - float(accept)) < 1e-9:
                        item["accepted"] = True
                except (TypeError, ValueError):
                    pass
            lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        if lines and accept is not None:
            # Ensure last tagged row is marked accepted if none matched.
            if not any('"accepted":true' in ln for ln in lines):
                last = json.loads(lines[-1])
                last["accepted"] = True
                lines[-1] = json.dumps(
                    last, ensure_ascii=False, separators=(",", ":")
                )

        self._frozen = SweetPSnapshot(
            score_at_accept=accept,
            band_at_accept=band_at_accept,
            minimum=minimum,
            maximum=maximum,
            average=average,
            sample_count=count,
            started_at=self._started_at,
            accepted_at=_utc_now(),
            filter_config=dict(self._filter_config),
            trace_lines=tuple(lines),
        )
        return self._frozen

    def empty_snapshot(self) -> SweetPSnapshot:
        return SweetPSnapshot(filter_config=dict(self._filter_config))
