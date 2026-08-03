"""DIP switch reader → MAIN / SWEETP / ERROR3."""

from __future__ import annotations

from .gpio_backend import GpioBackend
from .state import DipMode


def dip_mode_from_levels(*, dip1_on: bool, dip2_on: bool = False) -> DipMode:
    """DIP2 ON is always ERROR3. DIP1 selects MAIN vs SWEETP when DIP2 is OFF."""
    if dip2_on:
        return DipMode.ERROR3
    return DipMode.SWEETP if dip1_on else DipMode.MAIN


class DipReader:
    def __init__(
        self,
        gpio: GpioBackend,
        *,
        dip1_pin: int = 12,
        dip2_pin: int = 13,
        active_low: bool = True,
        pull_up: bool = True,
    ) -> None:
        self.gpio = gpio
        self.dip1_pin = dip1_pin
        self.dip2_pin = dip2_pin
        self.active_low = active_low
        self.gpio.setup_input(dip1_pin, pull_up=pull_up)
        self.gpio.setup_input(dip2_pin, pull_up=pull_up)

    def _is_on(self, pin: int) -> bool:
        high = self.gpio.read(pin)
        return (not high) if self.active_low else high

    def read_raw(self) -> tuple[bool, bool]:
        """Return (dip1_on, dip2_on)."""
        return self._is_on(self.dip1_pin), self._is_on(self.dip2_pin)

    def read_mode(self) -> DipMode:
        d1, d2 = self.read_raw()
        return dip_mode_from_levels(dip1_on=d1, dip2_on=d2)

    def describe(self) -> dict[str, str]:
        d1, d2 = self.read_raw()
        mode = dip_mode_from_levels(dip1_on=d1, dip2_on=d2)
        return {
            "dip1": "ON" if d1 else "OFF",
            "dip2": "ON" if d2 else "OFF",
            "dip2_note": "ERROR3 when ON" if d2 else "RESERVED (OFF = OK)",
            "mode": mode.value,
        }
