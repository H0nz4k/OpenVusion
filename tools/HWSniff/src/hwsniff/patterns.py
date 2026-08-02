"""Non-blocking LED pattern engine (no sleep in tick path)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class PatternKind(str, Enum):
    OFF = "off"
    ON = "on"
    SLOW = "slow"
    FAST = "fast"
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"


@dataclass
class _Channel:
    kind: PatternKind = PatternKind.OFF
    t0: float = 0.0
    finished: bool = False
    on_complete: Callable[[], None] | None = None


@dataclass
class PatternTimings:
    slow_ms: int = 500
    fast_ms: int = 100
    single_flash_ms: int = 150
    double_flash_ms: int = 150
    triple_flash_ms: int = 100


@dataclass
class PatternEngine:
    timings: PatternTimings = field(default_factory=PatternTimings)
    _channels: dict[str, _Channel] = field(default_factory=dict)
    _clock: Callable[[], float] = time.monotonic

    def set(
        self,
        name: str,
        kind: PatternKind | str,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        k = PatternKind(kind) if not isinstance(kind, PatternKind) else kind
        self._channels[name] = _Channel(
            kind=k,
            t0=self._clock(),
            finished=False,
            on_complete=on_complete,
        )

    def clear(self, name: str) -> None:
        self._channels.pop(name, None)

    def get_kind(self, name: str) -> PatternKind:
        ch = self._channels.get(name)
        return ch.kind if ch else PatternKind.OFF

    def tick(self, now: float | None = None) -> dict[str, bool]:
        """Return desired ON/OFF for each known channel. Never blocks."""
        now = self._clock() if now is None else now
        out: dict[str, bool] = {}
        for name, ch in list(self._channels.items()):
            on, done = self._eval(ch, now)
            out[name] = on
            if done and not ch.finished:
                ch.finished = True
                cb = ch.on_complete
                ch.on_complete = None
                if cb is not None:
                    cb()
        return out

    def _eval(self, ch: _Channel, now: float) -> tuple[bool, bool]:
        elapsed_ms = (now - ch.t0) * 1000.0
        t = self.timings
        if ch.kind == PatternKind.OFF:
            return False, False
        if ch.kind == PatternKind.ON:
            return True, False
        if ch.kind == PatternKind.SLOW:
            period = max(1, t.slow_ms * 2)
            return (elapsed_ms % period) < t.slow_ms, False
        if ch.kind == PatternKind.FAST:
            period = max(1, t.fast_ms * 2)
            return (elapsed_ms % period) < t.fast_ms, False
        if ch.kind == PatternKind.SINGLE:
            # one short ON then finished OFF
            step = max(1, t.single_flash_ms)
            if elapsed_ms < step:
                return True, False
            return False, True
        if ch.kind == PatternKind.DOUBLE:
            # ON, OFF, ON, then finished OFF
            step = max(1, t.double_flash_ms)
            # 0-step ON, step-2step OFF, 2step-3step ON, then done
            if elapsed_ms < step:
                return True, False
            if elapsed_ms < 2 * step:
                return False, False
            if elapsed_ms < 3 * step:
                return True, False
            return False, True
        if ch.kind == PatternKind.TRIPLE:
            step = max(1, t.triple_flash_ms)
            # 3× (ON step + OFF step) = 6 steps
            total = 6 * step
            if elapsed_ms >= total:
                return False, True
            phase = int(elapsed_ms // step) % 2
            return phase == 0, False
        return False, False
