"""Logical LED control driven by PatternEngine + GPIO (HWSniff v2: 4 LEDs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .gpio_backend import GpioBackend
from .patterns import PatternEngine, PatternKind


@dataclass
class LedPins:
    green: int = 19
    yellow: int = 16
    red: int = 26
    blue: int = 20
    active_high: bool = True


LED_NAMES = ("green", "yellow", "red", "blue")


class LedController:
    def __init__(
        self,
        gpio: GpioBackend,
        pins: LedPins | None = None,
        engine: PatternEngine | None = None,
    ) -> None:
        self.gpio = gpio
        self.pins = pins or LedPins()
        self.engine = engine or PatternEngine()
        self._pin_map = {
            "green": self.pins.green,
            "yellow": self.pins.yellow,
            "red": self.pins.red,
            "blue": self.pins.blue,
        }
        for pin in self._pin_map.values():
            self.gpio.setup_output(pin, initial=False)

        for name in LED_NAMES:
            self.engine.set(name, PatternKind.OFF)

    def set_pattern(
        self,
        name: str,
        kind: PatternKind | str,
        *,
        on_complete=None,
        count: int | None = None,
    ) -> None:
        self.engine.set(name, kind, on_complete=on_complete, count=count)

    def all_off(self) -> None:
        for name in LED_NAMES:
            self.engine.set(name, PatternKind.OFF)
        self.tick()

    def apply_levels(self, levels: Mapping[str, bool]) -> None:
        for name, on in levels.items():
            pin = self._pin_map.get(name)
            if pin is None:
                continue
            drive = bool(on) if self.pins.active_high else (not bool(on))
            self.gpio.write(pin, drive)

    def tick(self, now: float | None = None) -> dict[str, bool]:
        levels = self.engine.tick(now)
        for name in LED_NAMES:
            levels.setdefault(name, False)
        self.apply_levels(levels)
        return levels

    def physical_on(self, name: str) -> bool:
        pin = self._pin_map[name]
        high = self.gpio.read(pin)
        return high if self.pins.active_high else (not high)
