"""DIP switch reader → MAIN / SWEETP / UPLOAD / ERROR3."""

from __future__ import annotations

from .gpio_backend import GpioBackend
from .state import DipMode


def dip_mode_from_levels(*, dip1_on: bool, dip2_on: bool = False) -> DipMode:
    """Map DIP levels to appliance mode.

    DIP1 OFF + DIP2 OFF → MAIN
    DIP1 ON  + DIP2 OFF → SWEETP
    DIP1 OFF + DIP2 ON  → UPLOAD (WiFi FTP)
    DIP1 ON  + DIP2 ON  → ERROR3
    """
    if dip1_on and dip2_on:
        return DipMode.ERROR3
    if dip2_on:
        return DipMode.UPLOAD
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
        note = {
            DipMode.MAIN: "OFF/OFF = MAIN",
            DipMode.SWEETP: "DIP1 ON = SWEETP",
            DipMode.UPLOAD: "DIP2 ON = WiFi upload",
            DipMode.ERROR3: "both ON = ERROR3",
        }.get(mode, "")
        return {
            "dip1": "ON" if d1 else "OFF",
            "dip2": "ON" if d2 else "OFF",
            "dip2_note": note,
            "mode": mode.value,
        }
