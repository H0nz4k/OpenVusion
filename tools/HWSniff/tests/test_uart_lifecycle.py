"""UART ownership / SweetP leave-enter / ERROR2 recovery tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hwsniff.app import HeadlessApp
from hwsniff.collector_service import MockCollector
from hwsniff.gpio_backend import MockGpioBackend
from hwsniff.network import NetworkMonitor
from hwsniff.reader_monitor import ReaderMonitor, ReaderPresence
from hwsniff.state import CollectorOutcome, DeviceState
from hwsniff.sweet_point import MockSweetPoint


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class ProbeCountingReader(ReaderMonitor):
    """Present by default; can force-fail probes and count force ticks."""

    def __init__(self, port: str = "/dev/ttyS0") -> None:
        self.port = port
        self.present = True
        self.force_fail = False
        self.force_probes = 0
        self.poll_seconds = 0.0

    def tick(self, now=None, *, force: bool = False):
        if force:
            self.force_probes += 1
        if self.force_fail or not self.present:
            return ReaderPresence(present=False, error="busy_or_missing")
        return ReaderPresence(present=True, port=self.port, version="TWN4")

    def probe(self):
        return self.tick(force=True)


class UartLifecycleTests(unittest.TestCase):
    DIP1 = 12

    def _app(self, reader: ReaderMonitor, tmp: str):
        gpio = MockGpioBackend()
        clock = Clock()
        sweet = MockSweetPoint(period_seconds=1000, clock=clock)
        app = HeadlessApp(
            config={
                "hardware_profile": "v2",
                "gpio_prefer_mock": True,
                "self_test": {"enabled": False},
                "data_root": tmp,
                "capture_root": str(Path(tmp) / "captures"),
                "log_root": str(Path(tmp) / "logs"),
                "collector": {"use_mock": True},
                "sweetp": {"use_mock": True},
            },
            gpio=gpio,
            collector=MockCollector(
                work_seconds=0.4,
                save_seconds=0.05,
                phase_seconds=0.05,
                outcome=CollectorOutcome.SUCCESS,
                clock=clock,
            ),
            sweet_point=sweet,
            clock=clock,
            sleep=lambda _d: None,
            loop_forever=False,
            network=NetworkMonitor(
                interface="missing0", poll_seconds=1000, clock=clock
            ),
            reader_monitor=reader,
            force_mock=True,
        )
        app.boot()
        return app, gpio, clock, sweet

    def test_leave_sweetp_keeps_port_despite_probe_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = ProbeCountingReader()
            app, gpio, clock, sweet = self._app(reader, tmp)
            gpio.set_input(self.DIP1, False)
            app.tick()
            self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
            self.assertEqual(app.runtime.reader_port, "/dev/ttyS0")
            probes_before = reader.force_probes
            # Simulate post-stop exclusive-busy during leave
            reader.force_fail = True
            gpio.set_input(self.DIP1, True)
            app.tick()
            self.assertEqual(app.runtime.device_state, DeviceState.READY)
            self.assertEqual(app.runtime.reader_port, "/dev/ttyS0")
            self.assertFalse(sweet.is_running())
            # Leave must not require a successful force probe when port known
            self.assertEqual(reader.force_probes, probes_before)

    def test_enter_sweetp_without_port_stays_error2(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = ProbeCountingReader()
            reader.present = False
            app, gpio, clock, sweet = self._app(reader, tmp)
            self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
            gpio.set_input(self.DIP1, False)
            app.tick()
            # DIP wants SWEETP but no port → remain ERROR2, never idle SweetP
            self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
            self.assertFalse(sweet.is_running())
            self.assertIsNone(app.runtime.reader_port)

    def test_hotplug_restores_dip_sweetp(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = ProbeCountingReader()
            reader.present = False
            app, gpio, clock, sweet = self._app(reader, tmp)
            gpio.set_input(self.DIP1, False)
            app.tick()
            self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
            reader.present = True
            clock.advance(1.1)
            app.tick()
            self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
            self.assertTrue(sweet.is_running())
            self.assertEqual(app.runtime.reader_port, "/dev/ttyS0")

    def test_rapid_dip_toggle_keeps_single_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = ProbeCountingReader()
            app, gpio, clock, sweet = self._app(reader, tmp)
            for _ in range(6):
                gpio.set_input(self.DIP1, False)
                app.tick()
                self.assertIn(
                    app.runtime.device_state,
                    (DeviceState.SWEETP, DeviceState.ERROR2),
                )
                if app.runtime.device_state == DeviceState.SWEETP:
                    self.assertEqual(app._uart_owner, "sweetp")
                gpio.set_input(self.DIP1, True)
                app.tick()
                self.assertEqual(app.runtime.device_state, DeviceState.READY)
                self.assertIsNone(app._uart_owner)
                self.assertEqual(app.runtime.reader_port, "/dev/ttyS0")
                clock.advance(0.1)
            self.assertEqual(app.runtime.reader_port, "/dev/ttyS0")


if __name__ == "__main__":
    unittest.main()
