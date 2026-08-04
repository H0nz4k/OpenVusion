"""START/STOP with debounce, short/long press, and dual-button restart chord."""

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
    RESTART_CHORD = "restart_chord"


@dataclass
class ButtonConfig:
    start_pin: int = 21
    stop_pin: int = 6
    active_low: bool = True
    pull_up: bool = True
    debounce_ms: int = 50
    shutdown_hold_seconds: float = 3.0
    chord_hold_seconds: float = 5.0
    chord_warn_seconds: float = 4.0


@dataclass
class ChordStatus:
    """Live dual-button hold state for LED warning / suppress logic."""

    both_held: bool = False
    held_seconds: float = 0.0
    warning: bool = False
    fired: bool = False
    suppress_singles: bool = False
    cancelled: bool = False


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
        self._chord_since: float | None = None
        self._chord_fired = False
        self._chord_need_release = False
        self._chord_suppress = False
        self._chord_cancelled = False
        self._last_chord = ChordStatus()

    def _raw_pressed(self, pin: int) -> bool:
        high = self.gpio.read(pin)
        return (not high) if self.config.active_low else high

    def chord_status(self) -> ChordStatus:
        return self._last_chord

    def poll(self) -> list[ButtonEvent]:
        now = self._clock()
        debounce = self.config.debounce_ms / 1000.0
        events: list[ButtonEvent] = []

        start_raw = self._raw_pressed(self.config.start_pin)
        stop_raw = self._raw_pressed(self.config.stop_pin)
        # Chord uses raw levels so release cancels immediately (no debounce lag).
        both_raw = start_raw and stop_raw

        # Arm / evaluate chord before emitting singles from this sample.
        cancelled = False
        if self._chord_need_release:
            if not start_raw and not stop_raw:
                self._chord_need_release = False
                self._chord_fired = False
                self._chord_suppress = False
                self._chord_since = None
            self._update(
                self._start,
                start_raw,
                now,
                debounce,
                short=ButtonEvent.START_SHORT,
                long=None,
                long_seconds=None,
                emit_short=False,
            )
            self._update(
                self._stop,
                stop_raw,
                now,
                debounce,
                short=ButtonEvent.STOP_SHORT,
                long=None,
                long_seconds=None,
                emit_short=False,
            )
            self._last_chord = ChordStatus(
                both_held=both_raw,
                held_seconds=0.0,
                warning=False,
                fired=True,
                suppress_singles=True,
            )
            return []

        if both_raw:
            if self._chord_since is None:
                self._chord_since = now
                self._chord_suppress = True
                self._start.long_fired = True
                self._stop.long_fired = True
            held = now - self._chord_since
            warn_at = float(self.config.chord_warn_seconds)
            hold_for = float(self.config.chord_hold_seconds)
            # Keep debounce tracks warm without emitting singles.
            self._update(
                self._start,
                start_raw,
                now,
                debounce,
                short=ButtonEvent.START_SHORT,
                long=None,
                long_seconds=None,
                emit_short=False,
            )
            self._update(
                self._stop,
                stop_raw,
                now,
                debounce,
                short=ButtonEvent.STOP_SHORT,
                long=None,
                long_seconds=None,
                emit_short=False,
            )
            if held >= hold_for and not self._chord_fired:
                self._chord_fired = True
                self._chord_need_release = True
                self._last_chord = ChordStatus(
                    both_held=True,
                    held_seconds=held,
                    warning=False,
                    fired=True,
                    suppress_singles=True,
                )
                return [ButtonEvent.RESTART_CHORD]
            self._last_chord = ChordStatus(
                both_held=True,
                held_seconds=held,
                warning=held >= warn_at,
                fired=False,
                suppress_singles=True,
            )
            return []

        if self._chord_since is not None:
            cancelled = True
            self._chord_since = None
            self._chord_suppress = True
            self._start.long_fired = True
            self._stop.long_fired = True

        if self._chord_suppress and not start_raw and not stop_raw:
            self._chord_suppress = False

        block_singles = self._chord_suppress
        events.extend(
            self._update(
                self._start,
                start_raw,
                now,
                debounce,
                short=ButtonEvent.START_SHORT,
                long=None,
                long_seconds=None,
                emit_short=not block_singles,
            )
        )
        events.extend(
            self._update(
                self._stop,
                stop_raw,
                now,
                debounce,
                short=ButtonEvent.STOP_SHORT,
                long=None if block_singles else ButtonEvent.STOP_LONG,
                long_seconds=None
                if block_singles
                else self.config.shutdown_hold_seconds,
                emit_short=not block_singles,
            )
        )

        self._last_chord = ChordStatus(
            both_held=False,
            held_seconds=0.0,
            warning=False,
            fired=False,
            suppress_singles=self._chord_suppress,
            cancelled=cancelled,
        )

        if self._chord_suppress:
            return []
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
        emit_short: bool = True,
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
                if (
                    emit_short
                    and track.press_since is not None
                    and not track.long_fired
                ):
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
