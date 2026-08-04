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
    HEARTBEAT = "heartbeat"  # short pulse every period (WLAN)
    ERROR3 = "error3"  # 3× blink then longer pause
    PHASE_A = "phase_a"  # first half of border period
    PHASE_B = "phase_b"  # second half of border period
    COUNT_BLINK = "count_blink"  # N full ON/OFF cycles then complete


@dataclass
class _Channel:
    kind: PatternKind = PatternKind.OFF
    t0: float = 0.0
    finished: bool = False
    on_complete: Callable[[], None] | None = None
    count: int | None = None
    step_ms: int | None = None


@dataclass
class PatternTimings:
    slow_ms: int = 500
    fast_ms: int = 250
    single_flash_ms: int = 150
    double_flash_ms: int = 150
    triple_flash_ms: int = 100
    border_ms: int = 250
    heartbeat_period_ms: int = 3000
    heartbeat_pulse_ms: int = 120
    error3_on_ms: int = 500
    error3_off_ms: int = 500
    error3_pause_ms: int = 1500
    count_blink_ms: int = 500
    count_blink_count: int = 5


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
        count: int | None = None,
        step_ms: int | None = None,
    ) -> None:
        k = PatternKind(kind) if not isinstance(kind, PatternKind) else kind
        self._channels[name] = _Channel(
            kind=k,
            t0=self._clock(),
            finished=False,
            on_complete=on_complete,
            count=count,
            step_ms=step_ms,
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
            step = max(1, t.single_flash_ms)
            if elapsed_ms < step:
                return True, False
            return False, True
        if ch.kind == PatternKind.DOUBLE:
            step = max(1, t.double_flash_ms)
            if elapsed_ms < step:
                return True, False
            if elapsed_ms < 2 * step:
                return False, False
            if elapsed_ms < 3 * step:
                return True, False
            return False, True
        if ch.kind == PatternKind.TRIPLE:
            step = max(1, t.triple_flash_ms)
            total = 6 * step
            if elapsed_ms >= total:
                return False, True
            phase = int(elapsed_ms // step) % 2
            return phase == 0, False
        if ch.kind == PatternKind.HEARTBEAT:
            period = max(1, t.heartbeat_period_ms)
            pulse = max(1, min(t.heartbeat_pulse_ms, period - 1))
            return (elapsed_ms % period) < pulse, False
        if ch.kind == PatternKind.ERROR3:
            on_ms = max(1, t.error3_on_ms)
            off_ms = max(1, t.error3_off_ms)
            pause = max(1, t.error3_pause_ms)
            # 3 × (ON + OFF) then pause OFF
            blink_span = 3 * (on_ms + off_ms)
            cycle = blink_span + pause
            pos = elapsed_ms % cycle
            if pos >= blink_span:
                return False, False
            step = on_ms + off_ms
            within = pos % step
            return within < on_ms, False
        if ch.kind == PatternKind.PHASE_A:
            period = max(1, t.border_ms * 2)
            return (elapsed_ms % period) < t.border_ms, False
        if ch.kind == PatternKind.PHASE_B:
            period = max(1, t.border_ms * 2)
            return (elapsed_ms % period) >= t.border_ms, False
        if ch.kind == PatternKind.COUNT_BLINK:
            step = max(1, int(ch.step_ms) if ch.step_ms is not None else t.count_blink_ms)
            n = ch.count if ch.count is not None else t.count_blink_count
            n = max(1, int(n))
            # Each cycle = ON step + OFF step
            total = n * 2 * step
            if elapsed_ms >= total:
                return False, True
            phase = int(elapsed_ms // step) % 2
            return phase == 0, False
        return False, False
