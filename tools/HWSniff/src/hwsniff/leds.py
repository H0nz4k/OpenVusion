"""Logical LED control driven by PatternEngine + GPIO."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .gpio_backend import GpioBackend
from .patterns import PatternEngine, PatternKind


@dataclass
class LedPins:
    green: int = 5
    yellow: int = 6
    red: int = 12
    blue: int = 13
    orange: int = 19
    active_high: bool = True


LED_NAMES = ("green", "yellow", "red", "blue", "orange")


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
            "orange": self.pins.orange,
        }
        for pin in self._pin_map.values():
            self.gpio.setup_output(pin, initial=False)
            self.engine.set(self._name_for_pin(pin), PatternKind.OFF)

        for name in LED_NAMES:
            self.engine.set(name, PatternKind.OFF)

    def _name_for_pin(self, pin: int) -> str:
        for name, p in self._pin_map.items():
            if p == pin:
                return name
        return str(pin)

    def set_pattern(
        self,
        name: str,
        kind: PatternKind | str,
        *,
        on_complete=None,
    ) -> None:
        self.engine.set(name, kind, on_complete=on_complete)

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
        # ensure all LEDs present
        for name in LED_NAMES:
            levels.setdefault(name, False)
        self.apply_levels(levels)
        return levels

    def physical_on(self, name: str) -> bool:
        pin = self._pin_map[name]
        high = self.gpio.read(pin)
        return high if self.pins.active_high else (not high)
