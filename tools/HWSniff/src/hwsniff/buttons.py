"""START/STOP with debounce and short/long press detection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .gpio_backend import GpioBackend


class ButtonEvent(str, Enum):
    START_SHORT = "start_short"
    STOP_SHORT = "stop_short"
    STOP_LONG = "stop_long"


@dataclass
class ButtonConfig:
    start_pin: int = 17
    stop_pin: int = 27
    active_low: bool = True
    pull_up: bool = True
    debounce_ms: int = 50
    shutdown_hold_seconds: float = 3.0


@dataclass
class _BtnTrack:
    stable: bool | None = None
    pending: bool | None = None
    pending_since: float = 0.0
    press_since: float | None = None
    long_fired: bool = False


class ButtonWatcher:
    def __init__(
        self,
        gpio: GpioBackend,
        config: ButtonConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.gpio = gpio
        self.config = config or ButtonConfig()
        self._clock = clock
        self.gpio.setup_input(self.config.start_pin, pull_up=self.config.pull_up)
        self.gpio.setup_input(self.config.stop_pin, pull_up=self.config.pull_up)
        self._start = _BtnTrack()
        self._stop = _BtnTrack()

    def _raw_pressed(self, pin: int) -> bool:
        high = self.gpio.read(pin)
        return (not high) if self.config.active_low else high

    def poll(self) -> list[ButtonEvent]:
        now = self._clock()
        debounce = self.config.debounce_ms / 1000.0
        events: list[ButtonEvent] = []
        events.extend(
            self._update(
                self._start,
                self._raw_pressed(self.config.start_pin),
                now,
                debounce,
                short=ButtonEvent.START_SHORT,
                long=None,
                long_seconds=None,
            )
        )
        events.extend(
            self._update(
                self._stop,
                self._raw_pressed(self.config.stop_pin),
                now,
                debounce,
                short=ButtonEvent.STOP_SHORT,
                long=ButtonEvent.STOP_LONG,
                long_seconds=self.config.shutdown_hold_seconds,
            )
        )
        return events

    def _update(
        self,
        track: _BtnTrack,
        raw: bool,
        now: float,
        debounce: float,
        *,
        short: ButtonEvent,
        long: ButtonEvent | None,
        long_seconds: float | None,
    ) -> list[ButtonEvent]:
        events: list[ButtonEvent] = []
        if track.stable is None:
            # First sample: if already held (float / stuck / noise),
            # do NOT arm long-press — wait for a clean release→press edge.
            track.stable = raw
            track.press_since = None
            track.long_fired = bool(raw)
            return events

        if raw != track.stable:
            if track.pending != raw:
                track.pending = raw
                track.pending_since = now
                return events
            if now - track.pending_since < debounce:
                return events
            was = track.stable
            track.stable = raw
            track.pending = None
            if raw and not was:
                track.press_since = now
                track.long_fired = False
            elif not raw and was:
                if track.press_since is not None and not track.long_fired:
                    events.append(short)
                track.press_since = None
            return events

        if (
            raw
            and long is not None
            and long_seconds is not None
            and track.press_since is not None
            and not track.long_fired
            and (now - track.press_since) >= long_seconds
        ):
            track.long_fired = True
            events.append(long)
        return events
