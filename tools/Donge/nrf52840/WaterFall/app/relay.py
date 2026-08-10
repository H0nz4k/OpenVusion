from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RelayStatus:
    available: bool = False
    power_on: bool = False
    error: str = ""


class RelayController:
    def __init__(self, gpio_bcm: int, active_low: bool, default_power_on: bool = True):
        self.gpio_bcm = gpio_bcm
        self.active_low = active_low
        self.status = RelayStatus()
        self._dev = None

        try:
            from gpiozero import OutputDevice
            self._dev = OutputDevice(
                gpio_bcm,
                active_high=not active_low,
                initial_value=default_power_on,
            )
            self.status.available = True
            self.status.power_on = default_power_on
        except Exception as exc:
            self.status.error = f"{type(exc).__name__}: {exc}"

    def set_power(self, on: bool) -> RelayStatus:
        if not self._dev:
            return self.status

        if on:
            self._dev.on()
        else:
            self._dev.off()

        self.status.power_on = on
        return self.status
