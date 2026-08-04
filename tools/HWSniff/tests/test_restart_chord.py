"""START+STOP 5s service restart chord tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hwsniff.app import HeadlessApp
from hwsniff.buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from hwsniff.collector_service import MockCollector
from hwsniff.gpio_backend import MockGpioBackend
from hwsniff.network import NetworkMonitor
from hwsniff.patterns import PatternKind
from hwsniff.reader_monitor import ReaderMonitor, ReaderPresence
from hwsniff.service_restart import (
    SERVICE_RESTART_EXIT_CODE,
    write_restart_marker,
)
from hwsniff.state import CollectorOutcome, DeviceState, DipMode
from hwsniff.sweet_point import MockSweetPoint


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class AlwaysPresentReader(ReaderMonitor):
    def __init__(self, port: str = "/dev/ttyS0") -> None:
        self._p = ReaderPresence(present=True, port=port, version="TWN4")

    def tick(self, now=None, *, force: bool = False):
        return self._p

    def probe(self):
        return self._p


class ChordButtonTests(unittest.TestCase):
    def test_fires_at_five_seconds_and_suppresses_singles(self):
        gpio = MockGpioBackend()
        clock = Clock()
        w = ButtonWatcher(
            gpio,
            ButtonConfig(debounce_ms=10, chord_hold_seconds=5, chord_warn_seconds=4),
            clock=clock,
        )
        # Initial sample
        w.poll()
        gpio.set_input(21, False)
        gpio.set_input(6, False)
        clock.advance(0.02)
        self.assertEqual(w.poll(), [])  # debounce pending
        clock.advance(0.02)
        self.assertEqual(w.poll(), [])  # arm chord
        self.assertTrue(w.chord_status().both_held)
        clock.advance(3.9)
        self.assertEqual(w.poll(), [])
        self.assertFalse(w.chord_status().warning)
        clock.advance(0.2)  # past 4s warn
        self.assertEqual(w.poll(), [])
        self.assertTrue(w.chord_status().warning)
        clock.advance(1.0)  # past 5s
        self.assertEqual(w.poll(), [ButtonEvent.RESTART_CHORD])
        # Release one — no short
        gpio.set_input(21, True)
        clock.advance(0.05)
        self.assertEqual(w.poll(), [])
        gpio.set_input(6, True)
        clock.advance(0.05)
        self.assertEqual(w.poll(), [])

    def test_cancel_before_five(self):
        gpio = MockGpioBackend()
        clock = Clock()
        w = ButtonWatcher(
            gpio,
            ButtonConfig(debounce_ms=10, chord_hold_seconds=5, chord_warn_seconds=4),
            clock=clock,
        )
        w.poll()
        gpio.set_input(21, False)
        gpio.set_input(6, False)
        clock.advance(0.02)
        w.poll()
        clock.advance(0.02)
        w.poll()
        clock.advance(4.2)
        w.poll()
        self.assertTrue(w.chord_status().warning)
        gpio.set_input(21, True)
        clock.advance(0.05)
        ev = w.poll()
        self.assertEqual(ev, [])
        self.assertTrue(w.chord_status().cancelled or not w.chord_status().both_held)
        gpio.set_input(6, True)
        clock.advance(0.05)
        self.assertEqual(w.poll(), [])

    def test_rearm_after_full_release(self):
        gpio = MockGpioBackend()
        clock = Clock()
        w = ButtonWatcher(
            gpio,
            ButtonConfig(debounce_ms=10, chord_hold_seconds=5, chord_warn_seconds=4),
            clock=clock,
        )
        w.poll()
        gpio.set_input(21, False)
        gpio.set_input(6, False)
        clock.advance(0.02)
        w.poll()
        clock.advance(0.02)
        w.poll()
        clock.advance(5.1)
        self.assertEqual(w.poll(), [ButtonEvent.RESTART_CHORD])
        gpio.set_input(21, True)
        gpio.set_input(6, True)
        clock.advance(0.05)
        w.poll()
        gpio.set_input(21, False)
        gpio.set_input(6, False)
        clock.advance(0.02)
        w.poll()
        clock.advance(0.02)
        self.assertEqual(w.poll(), [])
        clock.advance(5.0)
        self.assertEqual(w.poll(), [ButtonEvent.RESTART_CHORD])


class ChordAppTests(unittest.TestCase):
    START = 21
    STOP = 6
    DIP1 = 12

    def _app(self, tmp: str, *, dip1: bool = False):
        gpio = MockGpioBackend()
        clock = Clock()
        marker = Path(tmp) / "restart.marker"
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
                "service_restart": {"marker_path": str(marker)},
                "gpio": {
                    "buttons": {
                        "debounce_ms": 10,
                        "chord_hold_seconds": 5,
                        "chord_warn_seconds": 4,
                    }
                },
            },
            gpio=gpio,
            collector=MockCollector(
                work_seconds=0.4,
                save_seconds=0.05,
                phase_seconds=0.05,
                outcome=CollectorOutcome.SUCCESS,
                clock=clock,
            ),
            sweet_point=MockSweetPoint(period_seconds=1000, clock=clock),
            clock=clock,
            sleep=lambda _d: None,
            loop_forever=False,
            network=NetworkMonitor(
                interface="missing0", poll_seconds=1000, clock=clock
            ),
            reader_monitor=AlwaysPresentReader(),
            force_mock=True,
        )
        if dip1:
            gpio.set_input(self.DIP1, False)
        app.boot()
        return app, gpio, clock, marker

    def _arm_chord(self, gpio, app, clock):
        gpio.set_input(self.START, False)
        gpio.set_input(self.STOP, False)
        clock.advance(0.02)
        app.tick()
        clock.advance(0.02)
        app.tick()

    def _hold_both(self, gpio, app, clock, seconds: float, step: float = 0.05):
        self._arm_chord(gpio, app, clock)
        elapsed = 0.0
        while elapsed < seconds:
            clock.advance(step)
            elapsed += step
            app.tick()
            if app._stop_loop:
                break

    def test_restart_after_five_with_four_red_blinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, marker = self._app(tmp)
            self.assertEqual(app.runtime.device_state, DeviceState.READY)
            self._arm_chord(gpio, app, clock)
            t_arm = clock.t
            # Advance into warning window
            while clock.t < t_arm + 4.05:
                clock.advance(0.05)
                app.tick()
            self.assertTrue(app._chord_warning_active)
            self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.COUNT_BLINK)
            ch = app.leds.engine._channels["red"]
            self.assertEqual(ch.count, 4)
            self.assertEqual(ch.step_ms, 125)
            # Pattern: 4× (125ms ON + 125ms OFF) = 1000ms. Sample mid-ON of each blink.
            warn_t0 = ch.t0
            for i in range(4):
                mid_on = warn_t0 + (i * 0.250) + 0.05
                clock.t = mid_on
                self.assertTrue(
                    app.leds.tick(clock.t)["red"],
                    f"expected red ON for blink {i + 1}",
                )
                mid_off = warn_t0 + (i * 0.250) + 0.18
                clock.t = mid_off
                self.assertFalse(
                    app.leds.tick(clock.t)["red"],
                    f"expected red OFF after blink {i + 1}",
                )
            # Complete to 5s from arm
            clock.t = t_arm + 5.15
            app.tick()
            self.assertTrue(app._stop_loop)
            self.assertEqual(app._restart_exit_code, SERVICE_RESTART_EXIT_CODE)
            self.assertTrue(marker.is_file())

    def test_cancel_restores_leds(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, _marker = self._app(tmp)
            self._arm_chord(gpio, app, clock)
            t_arm = clock.t
            while clock.t < t_arm + 4.1:
                clock.advance(0.05)
                app.tick()
            self.assertTrue(app._chord_warning_active)
            gpio.set_input(self.START, True)
            clock.advance(0.05)
            app.tick()
            self.assertFalse(app._stop_loop)
            self.assertFalse(app._chord_warning_active)
            self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_singles_suppressed_during_chord(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, _marker = self._app(tmp)
            self._arm_chord(gpio, app, clock)
            clock.advance(1.0)
            app.tick()
            # Release both early — must not start positioning
            gpio.set_input(self.START, True)
            gpio.set_input(self.STOP, True)
            clock.advance(0.05)
            app.tick()
            self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_restart_from_sweetp_error2_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            for setup in ("ready", "sweetp", "error2", "upload"):
                with self.subTest(setup=setup):
                    app, gpio, clock, marker = self._app(tmp)
                    marker.unlink(missing_ok=True)
                    if setup == "sweetp":
                        gpio.set_input(self.DIP1, False)
                        app.tick()
                        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
                    elif setup == "error2":
                        app.runtime.reader_port = None
                        app._enter(DeviceState.ERROR2)
                    elif setup == "upload":
                        gpio.set_input(13, False)
                        app.tick()
                        self.assertEqual(app.runtime.device_state, DeviceState.UPLOAD)
                    self._hold_both(gpio, app, clock, 5.2)
                    self.assertTrue(app._stop_loop)
                    self.assertEqual(
                        app._restart_exit_code, SERVICE_RESTART_EXIT_CODE
                    )
                    self.assertTrue(marker.is_file())

    def test_boot_with_marker_allows_sweetp(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "restart.marker"
            write_restart_marker(marker)
            gpio = MockGpioBackend()
            clock = Clock()
            gpio.set_input(self.DIP1, False)  # SWEETP at boot
            app = HeadlessApp(
                config={
                    "hardware_profile": "v2",
                    "gpio_prefer_mock": True,
                    "self_test": {"enabled": False},
                    "data_root": tmp,
                    "capture_root": str(Path(tmp) / "c"),
                    "log_root": str(Path(tmp) / "l"),
                    "collector": {"use_mock": True},
                    "sweetp": {"use_mock": True},
                    "service_restart": {"marker_path": str(marker)},
                },
                gpio=gpio,
                collector=MockCollector(clock=clock),
                sweet_point=MockSweetPoint(period_seconds=1000, clock=clock),
                clock=clock,
                sleep=lambda _d: None,
                loop_forever=False,
                network=NetworkMonitor(
                    interface="missing0", poll_seconds=1000, clock=clock
                ),
                reader_monitor=AlwaysPresentReader(),
                force_mock=True,
            )
            app.boot()
            self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
            self.assertFalse(marker.exists())
            self.assertEqual(app.runtime.dip_mode, DipMode.SWEETP)

    def test_cold_boot_sweetp_still_error3(self):
        with tempfile.TemporaryDirectory() as tmp:
            gpio = MockGpioBackend()
            clock = Clock()
            gpio.set_input(self.DIP1, False)
            app = HeadlessApp(
                config={
                    "hardware_profile": "v2",
                    "gpio_prefer_mock": True,
                    "self_test": {"enabled": False},
                    "data_root": tmp,
                    "capture_root": str(Path(tmp) / "c"),
                    "log_root": str(Path(tmp) / "l"),
                    "collector": {"use_mock": True},
                    "sweetp": {"use_mock": True},
                    "service_restart": {
                        "marker_path": str(Path(tmp) / "no-marker")
                    },
                },
                gpio=gpio,
                collector=MockCollector(clock=clock),
                sweet_point=MockSweetPoint(period_seconds=1000, clock=clock),
                clock=clock,
                sleep=lambda _d: None,
                loop_forever=False,
                network=NetworkMonitor(
                    interface="missing0", poll_seconds=1000, clock=clock
                ),
                reader_monitor=AlwaysPresentReader(),
                force_mock=True,
            )
            app.boot()
            self.assertEqual(app.runtime.device_state, DeviceState.ERROR3)


if __name__ == "__main__":
    unittest.main()
