"""Unit tests for Pi Zero headless GPIO HWSniff (no hardware)."""

from __future__ import annotations

import unittest

from hwsniff.app import HeadlessApp
from hwsniff.buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from hwsniff.collector_service import MockCollector
from hwsniff.configuration import DEFAULT_CONFIG
from hwsniff.dip import DipReader, dip_mode_from_levels
from hwsniff.gpio_backend import GpioZeroBackend, MockGpioBackend
from hwsniff.gpio_test import run_gpio_test
from hwsniff.network import NetworkMonitor, probe_wlan
from hwsniff.patterns import PatternEngine, PatternKind, PatternTimings
from hwsniff.state import (
    CollectorOutcome,
    DeviceState,
    DipMode,
    SweetQuality,
    WlanStatus,
)
from hwsniff.sweet_point import MockSweetPoint, quality_to_led_levels


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
        self.assertEqual(g["buttons"]["shutdown_hold_seconds"], 3)


class GpioZeroLevelTests(unittest.TestCase):
    def test_gpiozero_value_converted_to_electrical_high(self):
        """gpiozero .value is is_active; read() must return electrical HIGH."""

        class FakePin:
            def __init__(self) -> None:
                self.state = 1  # electrical HIGH (released, pull-up)

        class FakeInput:
            def __init__(self) -> None:
                self.pin = FakePin()
                self.value = False  # not active when HIGH + pull_up
                self.pull_up = True

            def close(self) -> None:
                pass

        backend = object.__new__(GpioZeroBackend)
        backend._inputs = {17: FakeInput()}
        backend._outputs = {}
        backend._input_pull_up = {17: True}
        self.assertTrue(backend.read(17))

        backend._inputs[17].pin.state = 0  # pressed to GND
        backend._inputs[17].value = True
        self.assertFalse(backend.read(17))

        # Without pin.state, fall back to inverting is_active for pull_up
        backend._inputs[17].pin = None
        backend._inputs[17].value = False
        self.assertTrue(backend.read(17))
        backend._inputs[17].value = True
        self.assertFalse(backend.read(17))


class DipTests(unittest.TestCase):
    def test_dip1_off_main(self):
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=False), DipMode.MAIN
        )
        # DIP2 ignored / reserved
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=True), DipMode.MAIN
        )

    def test_dip1_on_sweet_point(self):
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=False), DipMode.SWEET_POINT
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=True), DipMode.SWEET_POINT
        )

    def test_reader_active_low(self):
        gpio = MockGpioBackend()
        dip = DipReader(gpio, dip1_pin=22, dip2_pin=18, active_low=True)
        self.assertEqual(dip.read_mode(), DipMode.MAIN)
        gpio.set_input(22, False)  # DIP1 ON
        self.assertEqual(dip.read_mode(), DipMode.SWEET_POINT)
        gpio.set_input(18, False)  # DIP2 ON still SWEET_POINT
        self.assertEqual(dip.read_mode(), DipMode.SWEET_POINT)
        self.assertEqual(dip.describe()["dip2_note"], "RESERVED")


class SweetPointLedTests(unittest.TestCase):
    def test_quality_led_mapping(self):
        self.assertEqual(
            quality_to_led_levels(SweetQuality.HIGH),
            {"green": True, "orange": False, "red": False},
        )
        self.assertEqual(
            quality_to_led_levels(SweetQuality.MEDIUM),
            {"green": False, "orange": True, "red": False},
        )
        self.assertEqual(
            quality_to_led_levels(SweetQuality.LOW),
            {"green": False, "orange": False, "red": True},
        )
        self.assertEqual(
            quality_to_led_levels(SweetQuality.NONE),
            {"green": False, "orange": False, "red": False},
        )

    def test_mock_cycles_qualities(self):
        clock = Clock()
        mock = MockSweetPoint(period_seconds=1.0, clock=clock)
        mock.start()
        self.assertEqual(mock.tick(0.0).quality, SweetQuality.NONE)
        clock.advance(1.0)
        self.assertEqual(mock.tick(clock.t).quality, SweetQuality.LOW)
        clock.advance(1.0)
        self.assertEqual(mock.tick(clock.t).quality, SweetQuality.MEDIUM)
        clock.advance(1.0)
        self.assertEqual(mock.tick(clock.t).quality, SweetQuality.HIGH)


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

    def test_single_completes(self):
        clock = Clock()
        done = {"n": 0}
        eng = PatternEngine(timings=PatternTimings(single_flash_ms=150))
        eng._clock = clock
        eng.set("red", PatternKind.SINGLE, on_complete=lambda: done.__setitem__("n", 1))
        eng.tick(0.0)
        self.assertEqual(done["n"], 0)
        eng.tick(0.16)
        self.assertEqual(done["n"], 1)

    def test_triple_completes(self):
        clock = Clock()
        done = {"n": 0}
        eng = PatternEngine(timings=PatternTimings(triple_flash_ms=100))
        eng._clock = clock
        eng.set("green", PatternKind.TRIPLE, on_complete=lambda: done.__setitem__("n", 1))
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
    def test_long_stop_exactly_3_seconds(self):
        gpio = MockGpioBackend()
        clock = Clock()
        btn = ButtonWatcher(
            gpio,
            ButtonConfig(
                start_pin=17,
                stop_pin=27,
                debounce_ms=50,
                shutdown_hold_seconds=3,
            ),
            clock=clock,
        )
        btn.poll()
        gpio.press_active_low(27)
        btn.poll()
        clock.advance(0.06)
        btn.poll()
        clock.advance(2.9)
        self.assertEqual(btn.poll(), [])  # not yet long
        clock.advance(0.2)
        ev = btn.poll()
        self.assertIn(ButtonEvent.STOP_LONG, ev)

    def test_stop_held_at_boot_does_not_long_fire(self):
        gpio = MockGpioBackend()
        clock = Clock()
        gpio.press_active_low(27)  # already held before watcher starts
        btn = ButtonWatcher(
            gpio,
            ButtonConfig(
                start_pin=17,
                stop_pin=27,
                debounce_ms=50,
                shutdown_hold_seconds=3,
            ),
            clock=clock,
        )
        btn.poll()
        clock.advance(5.0)
        self.assertEqual(btn.poll(), [])
        # After release + new press, long stop works again
        gpio.release_active_low(27)
        btn.poll()
        clock.advance(0.06)
        btn.poll()
        gpio.press_active_low(27)
        btn.poll()
        clock.advance(0.06)
        btn.poll()
        clock.advance(3.1)
        self.assertIn(ButtonEvent.STOP_LONG, btn.poll())


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
            "mock_sweet_point": {"period_seconds": 1.0},
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
        gpio.press_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()

    def _finish_cancel(self, app: HeadlessApp, clock: Clock) -> None:
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break

    def test_ready_leds(self):
        app, gpio, clock = self._app()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertEqual(app.runtime.dip_mode, DipMode.MAIN)
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("green"))
        self.assertFalse(app.leds.physical_on("red"))

    def test_dip1_off_main_mode(self):
        app, gpio, clock = self._app()
        self.assertEqual(app.runtime.dip_mode, DipMode.MAIN)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_dip1_on_sweet_point_mode(self):
        app, gpio, clock = self._app()
        gpio.set_input(22, False)  # DIP1 ON
        app.tick()
        self.assertEqual(app.runtime.dip_mode, DipMode.SWEET_POINT)
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)

    def test_start_ignored_in_sweet_point(self):
        app, gpio, clock = self._app()
        gpio.set_input(22, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)
        self.assertFalse(app.collector.is_running())

    def test_sweet_point_led_mapping_green_orange_red(self):
        app, gpio, clock = self._app()
        gpio.set_input(22, False)
        app.tick()
        # force qualities through mock clock phases
        app.sweet_point._t0 = clock.t
        app.tick()
        self.assertEqual(app.runtime.sweet_quality, SweetQuality.NONE)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.OFF)
        self.assertEqual(app.leds.engine.get_kind("orange"), PatternKind.OFF)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.OFF)
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.OFF)

        clock.advance(1.0)
        app.tick()
        self.assertEqual(app.runtime.sweet_quality, SweetQuality.LOW)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.ON)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.OFF)

        clock.advance(1.0)
        app.tick()
        self.assertEqual(app.runtime.sweet_quality, SweetQuality.MEDIUM)
        self.assertEqual(app.leds.engine.get_kind("orange"), PatternKind.ON)

        clock.advance(1.0)
        app.tick()
        self.assertEqual(app.runtime.sweet_quality, SweetQuality.HIGH)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)

    def test_dip1_off_from_sweet_point_to_ready(self):
        app, gpio, clock = self._app()
        gpio.set_input(22, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)
        gpio.set_input(22, True)  # DIP1 OFF (pull-up HIGH)
        app.tick()
        self.assertEqual(app.runtime.dip_mode, DipMode.MAIN)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertFalse(app.sweet_point.is_running())
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)

    def test_dip_priority_over_start(self):
        app, gpio, clock = self._app()
        # Flip DIP1 ON in the same moment START would fire — DIP first in tick
        gpio.set_input(22, False)
        gpio.press_active_low(17)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(17)
        app.tick()
        clock.advance(0.06)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)
        self.assertNotEqual(app.runtime.device_state, DeviceState.WAITING)

    def test_start_ready_to_waiting_yellow_slow(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.WAITING)
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.SLOW)

    def test_start_in_reading_ignored(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READING)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READING)

    def test_cancel_sequence_red_flash_green_confirm_ready(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)  # WAITING
        self._pulse(gpio, app, clock, 27)  # cancel
        self.assertEqual(app.runtime.device_state, DeviceState.CANCELLED)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.SINGLE)
        seen_green_single = False
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.leds.engine.get_kind("green") == PatternKind.SINGLE:
                seen_green_single = True
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertTrue(seen_green_single)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)

    def test_stop_reading_request_stop(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        self.assertTrue(app.collector.is_running())
        self._pulse(gpio, app, clock, 27)
        self.assertTrue(app.collector._stop)
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertEqual(app.runtime.last_outcome, CollectorOutcome.CANCELLED)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def _run_to_success_wait_ack(
        self, app: HeadlessApp, gpio: MockGpioBackend, clock: Clock
    ) -> None:
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        for _ in range(120):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.SUCCESS_WAIT_ACK:
                break
        self.assertEqual(app.runtime.last_outcome, CollectorOutcome.SUCCESS)
        self.assertEqual(app.runtime.device_state, DeviceState.SUCCESS_WAIT_ACK)

    def test_success_does_not_auto_return_to_ready(self):
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        for _ in range(60):
            clock.advance(0.1)
            app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SUCCESS_WAIT_ACK)
        self.assertFalse(app.collector.is_running())

    def test_success_wait_ack_green_and_orange_on(self):
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)
        self.assertEqual(app.leds.engine.get_kind("orange"), PatternKind.ON)
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.OFF)
        self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.OFF)

    def test_start_in_success_wait_ack_only_acks(self):
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        self._pulse(gpio, app, clock, 17)  # ACK — must not start capture
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertFalse(app.collector.is_running())
        self.assertNotEqual(app.runtime.device_state, DeviceState.WAITING)
        self.assertNotEqual(app.runtime.device_state, DeviceState.READING)

    def test_ack_turns_orange_off_green_on(self):
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertEqual(app.leds.engine.get_kind("orange"), PatternKind.OFF)
        self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.ON)

    def test_next_start_from_ready_starts_new_capture(self):
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        self._pulse(gpio, app, clock, 17)  # ACK → READY
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self._pulse(gpio, app, clock, 17)  # new MAIN cycle
        self.assertEqual(app.runtime.device_state, DeviceState.WAITING)

    def test_tag_during_success_wait_ack_does_nothing(self):
        """No automatic re-read; START is ACK only (alpha1 has no live tag poll)."""
        app, gpio, clock = self._app()
        self._run_to_success_wait_ack(app, gpio, clock)
        # Simulate "tag still present" time passing — no state change, no capture
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SUCCESS_WAIT_ACK)
        self.assertFalse(app.collector.is_running())
        # START acknowledges only — never jumps to READING
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertFalse(app.collector.is_running())

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

    def test_dip1_on_during_main_aborts_to_sweet(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READING)
        gpio.set_input(22, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEET_POINT)
        self.assertEqual(app.runtime.dip_mode, DipMode.SWEET_POINT)

    def test_long_stop_from_ready_stays_ready(self):
        app, gpio, clock = self._app()
        gpio.press_active_low(27)
        app.tick()
        clock.advance(0.06)
        app.tick()
        clock.advance(3.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertEqual(app._shutdown_hits["n"], 0)  # type: ignore[attr-defined]

    def test_long_stop_during_waiting_resets_to_ready(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.WAITING)
        gpio.press_active_low(27)
        app.tick()
        clock.advance(0.06)
        app.tick()
        clock.advance(3.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.CANCELLED)
        self._finish_cancel(app, clock)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertEqual(app._shutdown_hits["n"], 0)  # type: ignore[attr-defined]

    def test_long_stop_during_reading_resets_to_ready(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, 17)
        self._pulse(gpio, app, clock, 17)
        self.assertEqual(app.runtime.device_state, DeviceState.READING)
        gpio.press_active_low(27)
        app.tick()
        clock.advance(0.06)
        app.tick()
        clock.advance(3.1)
        app.tick()
        self._finish_cancel(app, clock)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        self.assertFalse(app.collector.is_running())
        self.assertEqual(app._shutdown_hits["n"], 0)  # type: ignore[attr-defined]

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
