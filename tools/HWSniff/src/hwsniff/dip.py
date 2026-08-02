"""DIP switch reader → DipMode mapping."""

from __future__ import annotations

from .gpio_backend import GpioBackend
from .state import DipMode


def dip_mode_from_levels(*, dip1_on: bool, dip2_on: bool) -> DipMode:
    """Map switch ON/OFF to working mode names."""
    if not dip1_on and not dip2_on:
        return DipMode.NORMAL
    if dip1_on and not dip2_on:
        return DipMode.FAST
    if not dip1_on and dip2_on:
        return DipMode.DEEP
    return DipMode.SERVICE


class DipReader:
    def __init__(
        self,
        gpio: GpioBackend,
        *,
        dip1_pin: int = 22,
        dip2_pin: int = 18,
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
            "mode": mode.value,
        }
