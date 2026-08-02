"""GPIO abstraction: real (gpiozero) + mock for tests / non-Pi hosts."""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class GpioBackend(Protocol):
    def setup_input(self, pin: int, *, pull_up: bool = True) -> None: ...

    def setup_output(self, pin: int, *, initial: bool = False) -> None: ...

    def read(self, pin: int) -> bool:
        """Return True when line is electrically HIGH."""

    def write(self, pin: int, value: bool) -> None:
        """Drive pin HIGH when value is True."""

    def close(self) -> None: ...


class MockGpioBackend:
    """In-memory GPIO for unit tests and --gpio-test dry runs on PC."""

    def __init__(self) -> None:
        self.inputs: dict[int, bool] = {}
        self.outputs: dict[int, bool] = {}
        self.pull_ups: set[int] = set()
        self.closed = False
        self.fail_setup = False

    def setup_input(self, pin: int, *, pull_up: bool = True) -> None:
        if self.fail_setup:
            raise RuntimeError("GPIO setup failed")
        if pull_up:
            self.pull_ups.add(pin)
            self.inputs.setdefault(pin, True)  # released / OFF default
        else:
            self.inputs.setdefault(pin, False)

    def setup_output(self, pin: int, *, initial: bool = False) -> None:
        if self.fail_setup:
            raise RuntimeError("GPIO setup failed")
        self.outputs[pin] = bool(initial)

    def read(self, pin: int) -> bool:
        if pin in self.outputs:
            return bool(self.outputs[pin])
        return bool(self.inputs.get(pin, True))

    def write(self, pin: int, value: bool) -> None:
        self.outputs[pin] = bool(value)

    def close(self) -> None:
        self.closed = True

    # Test helpers
    def set_input(self, pin: int, high: bool) -> None:
        self.inputs[pin] = bool(high)

    def press_active_low(self, pin: int) -> None:
        self.inputs[pin] = False

    def release_active_low(self, pin: int) -> None:
        self.inputs[pin] = True


class GpioZeroBackend:
    """gpiozero DigitalInputDevice / DigitalOutputDevice wrapper."""

    def __init__(self) -> None:
        try:
            from gpiozero import DigitalInputDevice, DigitalOutputDevice
        except ImportError as exc:  # pragma: no cover - Pi-only
            raise RuntimeError(
                "gpiozero is required on Raspberry Pi. "
                "Install: sudo apt install python3-gpiozero"
            ) from exc
        self._DigitalInput = DigitalInputDevice
        self._DigitalOutput = DigitalOutputDevice
        self._inputs: dict[int, object] = {}
        self._outputs: dict[int, object] = {}

    def setup_input(self, pin: int, *, pull_up: bool = True) -> None:
        if pin in self._inputs:
            return
        self._inputs[pin] = self._DigitalInput(
            pin, pull_up=pull_up, bounce_time=None
        )

    def setup_output(self, pin: int, *, initial: bool = False) -> None:
        if pin in self._outputs:
            return
        self._outputs[pin] = self._DigitalOutput(pin, initial_value=initial)

    def read(self, pin: int) -> bool:
        dev = self._inputs.get(pin) or self._outputs.get(pin)
        if dev is None:
            raise KeyError(f"GPIO {pin} not configured")
        return bool(getattr(dev, "value"))

    def write(self, pin: int, value: bool) -> None:
        dev = self._outputs.get(pin)
        if dev is None:
            raise KeyError(f"GPIO {pin} not configured as output")
        dev.value = bool(value)

    def close(self) -> None:
        for dev in list(self._inputs.values()) + list(self._outputs.values()):
            try:
                close = getattr(dev, "close", None)
                if close:
                    close()
            except Exception:  # noqa: BLE001
                pass
        self._inputs.clear()
        self._outputs.clear()


def create_backend(*, prefer_mock: bool = False) -> GpioBackend:
    if prefer_mock:
        return MockGpioBackend()
    try:
        return GpioZeroBackend()
    except Exception as exc:  # noqa: BLE001
        log.warning("Falling back to MockGpioBackend: %s", exc)
        return MockGpioBackend()
