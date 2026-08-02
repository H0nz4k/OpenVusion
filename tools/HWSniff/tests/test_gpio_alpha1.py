"""Unit tests for Pi Zero headless GPIO HWSniff (no hardware)."""

from __future__ import annotations

import unittest

from hwsniff.app import HeadlessApp
from hwsniff.buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from hwsniff.collector_service import MockCollector
from hwsniff.configuration import DEFAULT_CONFIG
from hwsniff.dip import DipReader, dip_mode_from_levels
from hwsniff.gpio_backend import MockGpioBackend
from hwsniff.gpio_test import run_gpio_test
from hwsniff.leds import LedController
from hwsniff.network import NetworkMonitor, probe_wlan
from hwsniff.patterns import PatternEngine, PatternKind, PatternTimings
from hwsniff.state import CollectorOutcome, DeviceState, DipMode, WlanStatus


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class GpioDefaultsTests(unittest.TestCase):
    def test_default_gpio_pins(self):
        g = DEFAULT_CONFIG["gpio"]
        self.assertEqual(g["buttons"]["start"], 17)
        self.assertEqual(g["buttons"]["stop"], 27)
        self.assertEqual(g["dip"]["dip1"], 22)
        self.assertEqual(g["dip"]["dip2"], 18)
        self.assertEqual(g["leds"]["green"], 5)
        self.assertEqual(g["leds"]["yellow"], 6)
        self.assertEqual(g["leds"]["red"], 12)
        self.assertEqual(g["leds"]["blue"], 13)
        self.assertEqual(g["leds"]["orange"], 19)


class DipTests(unittest.TestCase):
    def test_mode_mapping(self):
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=False), DipMode.NORMAL
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=False), DipMode.FAST
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=True), DipMode.DEEP
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=True), DipMode.SERVICE
        )

    def test_reader_active_low(self):
        gpio = MockGpioBackend()
        dip = DipReader(gpio, dip1_pin=22, dip2_pin=18, active_low=True)
        # pull-up default HIGH = OFF
        self.assertEqual(dip.read_mode(), DipMode.NORMAL)
        gpio.set_input(22, False)  # DIP1 ON
        self.assertEqual(dip.read_mode(), DipMode.FAST)
        gpio.set_input(18, False)
        self.assertEqual(dip.read_mode(), DipMode.SERVICE)


class PatternTests(unittest.TestCase):
    def test_non_blocking_slow_fast(self):
        clock = Clock()
        eng = PatternEngine(timings=PatternTimings(slow_ms=500, fast_ms=100))
        eng._clock = clock
        eng.set("yellow", PatternKind.SLOW)
        self.assertTrue(eng.tick(0.0)["yellow"])
        self.assertFalse(eng.tick(0.6)["yellow"])
        eng.set("yellow", PatternKind.FAST)
        clock.t = 10.0
        eng.set("yellow", PatternKind.FAST)
        self.assertTrue(eng.tick(10.0)["yellow"])
        self.assertFalse(eng.tick(10.15)["yellow"])

    def test_triple_completes(self):
        clock = Clock()
        done = {"n": 0}
        eng = PatternEngine(timings=PatternTimings(triple_flash_ms=100))
        eng._clock = clock
        eng.set("green", PatternKind.TRIPLE, on_complete=lambda: done.__setitem__("n", 1))
        # 6 * 100ms = 600ms
        for ms in range(0, 700, 50):
            clock.t = ms / 1000.0
            eng.tick(clock.t)
        self.assertEqual(done["n"], 1)


class NetworkTests(unittest.TestCase):
    def test_missing_iface_offline(self):
        status, ip = probe_wlan("wlan_does_not_exist_zz")
        self.assertEqual(status, WlanStatus.OFFLINE)
        self.assertIsNone(ip)

    def test_monitor_does_not_crash(self):
        mon = NetworkMonitor(interface="nope0", poll_seconds=0)
        mon.tick()
        self.assertEqual(mon.status, WlanStatus.OFFLINE)


class ButtonTests(unittest.TestCase):
    def test_short_and_long_stop(self):
        gpio = MockGpioBackend()
        clock = Clock()
        btn = ButtonWatcher(
            gpio,
            ButtonConfig(
                start_pin=17,
                stop_pin=27,
                debounce_ms=50,
                shutdown_hold_seconds=4,
            ),
            clock=clock,
        )
        btn.poll()
        gpio.press_active_low(17)
        btn.poll()
        clock.advance(0.06)
        self.assertEqual(btn.poll(), [])  # pressed, no short yet
        gpio.release_active_low(17)
        btn.poll()
        clock.advance(0.06)
        ev = btn.poll()
        self.assertIn(ButtonEvent.START_SHORT, ev)

        gpio.press_active_low(27)
        btn.poll()
        clock.advance(0.06)
        btn.poll()
        clock.advance(4.1)
        ev = btn.poll()
        self.assertIn(ButtonEvent.STOP_LONG, ev)


class AppStateMachineTests(unittest.TestCase):
    def _app(self, **kwargs) -> tuple[HeadlessApp, MockGpioBackend, Clock]:
        gpio = MockGpioBackend()
        clock = Clock()
        cfg = {
            "gpio_prefer_mock": True,
            "self_test": {"enabled": False},
            "data_root": kwargs.pop("data_root", None),
            "mock_collector": {
                "work_seconds": 0.2,
                "save_seconds": 0.05,
                "outcome": "SUCCESS",
            },
            "network": {"poll_seconds": 1000},
        }
        if cfg["data_root"] is None:
            import tempfile
            from pathlib import Path

            tmp = tempfile.mkdtemp()
            cfg["data_root"] = tmp
            cfg["log_root"] = str(Path(tmp) / "logs")

        shutdown = {"n": 0}

        coll = MockCollector(
            work_seconds=0.15,
            save_seconds=0.05,
            outcome=CollectorOutcome.SUCCESS,
            clock=clock,
        )
        app = HeadlessApp(
            config=cfg,
            gpio=gpio,
            collector=coll,
            shutdown_callback=lambda: shutdown.__setitem__("n", shutdown["n"] + 1),
            clock=clock,
            sleep=lambda _d: None,
            loop_forever=False,
            network=NetworkMonitor(interface="missing0", poll_seconds=1000, clock=clock),
        )
        app._shutdown_hits = shutdown  # type: ignore[attr-defined]
        app.boot()
        return app, gpio, clock

    def _pulse(self, gpio: MockGpioBackend, app: HeadlessApp, clock: Clock, pin: int):
        # Debounce needs: edge observe → wait → commit (two polls per edge).
        gpio.press_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()

    def test_ready_leds(self):
        app, gpio, clock = self._app()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("green"))
        self.assertFalse(app.leds.physical_on("red"))

    def test_start_ready_to_waiting_yellow_slow(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.WAITING)
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.SLOW)

    def test_start_in_reading_ignored(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)  # WAITING
        self._pulse(gpio, app, clock, 17)  # READING
        self.assertEqual(app.runtime.device_state, DeviceState.READING)
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.FAST)
        self._pulse(gpio, app, clock, 17)  # ignore
        self.assertEqual(app.runtime.device_state, DeviceState.READING)

    def test_stop_waiting_cancelled_ready(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 27)
        self.assertEqual(app.runtime.device_state, DeviceState.CANCELLED)
        # finish double flash (~450 ms)
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_stop_reading_request_stop(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        self.assertTrue(app.collector.is_running())
        self._pulse(gpio, app, clock, 27)
        self.assertTrue(app.collector._stop)
        for _ in range(30):
            clock.advance(0.05)
            app.tick()
        self.assertEqual(app.runtime.last_outcome, CollectorOutcome.CANCELLED)

    def test_success_path(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        for _ in range(120):
            clock.advance(0.05)
            app.tick()
            if (
                app.runtime.last_outcome == CollectorOutcome.SUCCESS
                and app.runtime.device_state == DeviceState.READY
            ):
                break
        self.assertEqual(app.runtime.last_outcome, CollectorOutcome.SUCCESS)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_partial_leds(self):
        app, gpio, clock = self._app()
        app.collector.default_outcome = CollectorOutcome.PARTIAL
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        for _ in range(80):
            clock.advance(0.05)
            app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.PARTIAL)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.SLOW)

    def test_error_leds(self):
        app, gpio, clock = self._app()
        app.collector.default_outcome = CollectorOutcome.FAILED
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        for _ in range(80):
            clock.advance(0.05)
            app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.ON)

    def test_wlan_led_mapping(self):
        app, gpio, clock = self._app()
        app.runtime.wlan = WlanStatus.CONNECTED
        app._apply_wlan_led()
        self.assertEqual(app.leds.engine.get_kind("blue"), PatternKind.ON)
        app.runtime.wlan = WlanStatus.CONNECTING
        app._apply_wlan_led()
        self.assertEqual(app.leds.engine.get_kind("blue"), PatternKind.SLOW)
        app.runtime.wlan = WlanStatus.OFFLINE
        app._apply_wlan_led()
        self.assertEqual(app.leds.engine.get_kind("blue"), PatternKind.OFF)

    def test_dip_locked_during_reading(self):
        app, gpio, clock = self._app()
        # NORMAL
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.active_cycle_mode, DipMode.NORMAL)
        self._pulse(gpio, app, clock, 17)  # READING
        gpio.set_input(22, False)  # DIP1 ON
        gpio.set_input(18, False)  # DIP2 ON → SERVICE if re-read
        clock.advance(0.1)
        app.tick()
        self.assertEqual(app.runtime.active_cycle_mode, DipMode.NORMAL)
        # finish cycle through SUCCESS_SIGNAL → READY
        for _ in range(120):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        # new START rereads DIP
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.active_cycle_mode, DipMode.SERVICE)

    def test_long_stop_shutdown_callback(self):
        app, gpio, clock = self._app()
        gpio.press_active_low(27)
        app.tick()
        clock.advance(0.06)
        app.tick()
        clock.advance(4.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SHUTDOWN)
        self.assertEqual(app._shutdown_hits["n"], 1)  # type: ignore[attr-defined]

    def test_gpio_fail_during_construct(self):
        gpio = MockGpioBackend()
        gpio.fail_setup = True
        with self.assertRaises(RuntimeError):
            HeadlessApp(
                config={"self_test": {"enabled": False}},
                gpio=gpio,
                sleep=lambda _d: None,
                loop_forever=False,
            )

    def test_boot_gpio_error_to_error_state(self):
        """If boot health fails after construct, land in ERROR."""
        app, gpio, clock = self._app()
        app._gpio_ok = False
        app.boot()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.ON)


class GpioTestCliTests(unittest.TestCase):
    def test_gpio_test_mock_passes(self):
        code = run_gpio_test(
            {"gpio_prefer_mock": True, "self_test": {"enabled": False}},
            gpio=MockGpioBackend(),
            wait_buttons=True,
            sleep=lambda _d: None,
        )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
