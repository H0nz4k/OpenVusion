"""Unit tests for HWSniff v2 state machine, SweetP bands, READ progress, DIP."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hwsniff.app import HeadlessApp
from hwsniff.buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from hwsniff.collector_service import MockCollector
from hwsniff.configuration import (
    DEFAULT_CONFIG,
    ConfigError,
    load_config,
    validate_config,
)
from hwsniff.dip import DipReader, dip_mode_from_levels
from hwsniff.gpio_backend import MockGpioBackend
from hwsniff.gpio_test import run_gpio_test
from hwsniff.network import NetworkMonitor
from hwsniff.patterns import PatternEngine, PatternKind, PatternTimings
from hwsniff.reader_monitor import ReaderMonitor, ReaderPresence
from hwsniff.state import (
    CollectorOutcome,
    DeviceState,
    DipMode,
    SweetBand,
    WlanStatus,
)
from hwsniff.sweet_point import MockSweetPoint
from hwsniff.sweetp_bands import (
    SweetPThresholds,
    band_from_score,
    score_allows_read,
)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class AlwaysPresentReader(ReaderMonitor):
    def __init__(self, port: str = "/dev/ttyACM0") -> None:
        self._presence = ReaderPresence(present=True, port=port, version="TWN4 Fake")
        self.poll_seconds = 1.0
        self._clock = lambda: 0.0
        self._next = 0.0

    def tick(self, now=None, *, force: bool = False):
        return self._presence

    def probe(self):
        return self._presence


class AbsentReader(ReaderMonitor):
    def __init__(self) -> None:
        self._presence = ReaderPresence(present=False, error="no_reader")
        self.poll_seconds = 1.0
        self._clock = lambda: 0.0
        self._next = 0.0
        self.force_present: ReaderPresence | None = None

    def tick(self, now=None, *, force: bool = False):
        if self.force_present is not None:
            return self.force_present
        return self._presence

    def probe(self):
        return self.tick(force=True)


class ToggleableReader(ReaderMonitor):
    """Starts present; tests flip ``present`` to simulate hotplug."""

    def __init__(self, port: str = "/dev/ttyACM0") -> None:
        self.port = port
        self.present = True
        self.poll_seconds = 0.0  # every tick
        self._clock = lambda: 0.0
        self._next = 0.0

    def tick(self, now=None, *, force: bool = False):
        if self.present:
            return ReaderPresence(present=True, port=self.port, version="TWN4 Fake")
        return ReaderPresence(present=False, error="unplugged")

    def probe(self):
        return self.tick(force=True)


class GpioDefaultsTests(unittest.TestCase):
    def test_default_gpio_pins_v2(self):
        g = DEFAULT_CONFIG["gpio"]
        self.assertEqual(DEFAULT_CONFIG["hardware_profile"], "v2")
        self.assertEqual(g["buttons"]["start"], 5)
        self.assertEqual(g["buttons"]["stop"], 6)
        self.assertEqual(g["dip"]["dip1"], 12)
        self.assertEqual(g["dip"]["dip2"], 13)
        self.assertEqual(g["leds"]["green"], 19)
        self.assertEqual(g["leds"]["yellow"], 16)
        self.assertEqual(g["leds"]["red"], 26)
        self.assertEqual(g["leds"]["blue"], 20)
        self.assertNotIn("orange", g["leds"])

    def test_legacy_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(
                '{"version":"1.0-alpha1","gpio":{"buttons":{"start":17,"stop":27},'
                '"dip":{"dip1":22,"dip2":18},"leds":{"green":5}}}',
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)


class DipTests(unittest.TestCase):
    def test_combinations(self):
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=False), DipMode.MAIN
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=False), DipMode.SWEETP
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=True), DipMode.ERROR3
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=True), DipMode.ERROR3
        )

    def test_reader_active_low(self):
        gpio = MockGpioBackend()
        dip = DipReader(gpio, dip1_pin=12, dip2_pin=13, active_low=True)
        self.assertEqual(dip.read_mode(), DipMode.MAIN)
        gpio.set_input(12, False)
        self.assertEqual(dip.read_mode(), DipMode.SWEETP)
        gpio.set_input(13, False)
        self.assertEqual(dip.read_mode(), DipMode.ERROR3)


class SweetPBandTests(unittest.TestCase):
    def test_thresholds(self):
        thr = SweetPThresholds()
        cases = [
            (100, True, SweetBand.GOOD),
            (75, True, SweetBand.GOOD),
            (74, True, SweetBand.USABLE),
            (56, True, SweetBand.USABLE),
            (55, True, SweetBand.BORDERLINE),
            (40, True, SweetBand.BORDERLINE),
            (39, True, SweetBand.BAD),
            (0, True, SweetBand.BAD),
            (None, False, SweetBand.NONE),
        ]
        for score, tag, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(
                    band_from_score(score, has_tag=tag, thresholds=thr),
                    expected,
                )

    def test_hysteresis(self):
        thr = SweetPThresholds(hysteresis=3)
        # Stay GOOD until drop below 72
        self.assertEqual(
            band_from_score(73, has_tag=True, previous=SweetBand.GOOD, thresholds=thr),
            SweetBand.GOOD,
        )
        self.assertEqual(
            band_from_score(71, has_tag=True, previous=SweetBand.GOOD, thresholds=thr),
            SweetBand.USABLE,
        )

    def test_read_minimum(self):
        self.assertTrue(score_allows_read(56, has_tag=True))
        self.assertFalse(score_allows_read(55, has_tag=True))
        self.assertFalse(score_allows_read(80, has_tag=False))


class PatternTests(unittest.TestCase):
    def test_error3_triple_then_pause(self):
        clock = Clock()
        eng = PatternEngine(
            timings=PatternTimings(
                error3_on_ms=500, error3_off_ms=500, error3_pause_ms=1500
            )
        )
        eng._clock = clock
        eng.set("red", PatternKind.ERROR3)
        # First ON
        self.assertTrue(eng.tick(0.0)["red"])
        # During first OFF
        self.assertFalse(eng.tick(0.6)["red"])
        # During pause after 3 blinks (3s blink span) at t=3.2
        self.assertFalse(eng.tick(3.2)["red"])

    def test_heartbeat(self):
        clock = Clock()
        eng = PatternEngine(
            timings=PatternTimings(heartbeat_period_ms=3000, heartbeat_pulse_ms=120)
        )
        eng._clock = clock
        eng.set("blue", PatternKind.HEARTBEAT)
        self.assertTrue(eng.tick(0.0)["blue"])
        self.assertFalse(eng.tick(0.2)["blue"])

    def test_count_blink_completes(self):
        clock = Clock()
        done = {"n": 0}
        eng = PatternEngine(timings=PatternTimings(count_blink_ms=100))
        eng._clock = clock
        eng.set(
            "green",
            PatternKind.COUNT_BLINK,
            count=5,
            on_complete=lambda: done.__setitem__("n", 1),
        )
        for ms in range(0, 1200, 50):
            clock.t = ms / 1000.0
            eng.tick(clock.t)
        self.assertEqual(done["n"], 1)

    def test_phase_a_b_alternate(self):
        clock = Clock()
        eng = PatternEngine(timings=PatternTimings(border_ms=250))
        eng._clock = clock
        eng.set("yellow", PatternKind.PHASE_A)
        eng.set("red", PatternKind.PHASE_B)
        levels = eng.tick(0.0)
        self.assertTrue(levels["yellow"])
        self.assertFalse(levels["red"])
        levels = eng.tick(0.3)
        self.assertFalse(levels["yellow"])
        self.assertTrue(levels["red"])


class AppHelpers:
    START = 5
    STOP = 6
    DIP1 = 12
    DIP2 = 13

    @staticmethod
    def _app(
        *,
        reader: ReaderMonitor | None = None,
        collector: MockCollector | None = None,
        sweet: MockSweetPoint | None = None,
        self_test: bool = False,
        dip1: bool = False,
        dip2: bool = False,
    ) -> tuple[HeadlessApp, MockGpioBackend, Clock]:
        gpio = MockGpioBackend()
        clock = Clock()
        tmp = tempfile.mkdtemp()
        cfg = {
            "hardware_profile": "v2",
            "gpio_prefer_mock": True,
            "self_test": {"enabled": self_test, "led_ms": 10, "cycles": 2},
            "data_root": tmp,
            "capture_root": str(Path(tmp) / "captures"),
            "log_root": str(Path(tmp) / "logs"),
            "collector": {"use_mock": True},
            "sweetp": {"use_mock": True},
            "network": {"poll_seconds": 1000},
        }
        coll = collector or MockCollector(
            work_seconds=0.9,
            save_seconds=0.05,
            phase_seconds=0.1,
            outcome=CollectorOutcome.SUCCESS,
            clock=clock,
        )
        sweet_point = sweet or MockSweetPoint(period_seconds=1000, clock=clock)
        app = HeadlessApp(
            config=cfg,
            gpio=gpio,
            collector=coll,
            sweet_point=sweet_point,
            clock=clock,
            sleep=lambda _d: None,
            loop_forever=False,
            network=NetworkMonitor(
                interface="missing0", poll_seconds=1000, clock=clock
            ),
            reader_monitor=reader or AlwaysPresentReader(),
            force_mock=True,
        )
        if dip1:
            gpio.set_input(AppHelpers.DIP1, False)
        if dip2:
            gpio.set_input(AppHelpers.DIP2, False)
        app.boot()
        return app, gpio, clock

    @staticmethod
    def _pulse(gpio, app, clock, pin):
        gpio.press_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()


class BootTests(unittest.TestCase, AppHelpers):
    def test_boot_self_test_two_cycles(self):
        seen = []

        class TrackingLedApp(HeadlessApp):
            def _led_self_test(self, led_ms, cycles=2):
                seen.append(cycles)
                super()._led_self_test(led_ms, cycles)

        gpio = MockGpioBackend()
        clock = Clock()
        tmp = tempfile.mkdtemp()
        app = TrackingLedApp(
            config={
                "hardware_profile": "v2",
                "gpio_prefer_mock": True,
                "self_test": {"enabled": True, "led_ms": 5, "cycles": 2},
                "data_root": tmp,
                "log_root": str(Path(tmp) / "logs"),
                "network": {"poll_seconds": 1000},
            },
            gpio=gpio,
            collector=MockCollector(clock=clock),
            sweet_point=MockSweetPoint(clock=clock),
            clock=clock,
            sleep=lambda _d: None,
            loop_forever=False,
            network=NetworkMonitor(interface="x", poll_seconds=1000, clock=clock),
            reader_monitor=AlwaysPresentReader(),
            force_mock=True,
        )
        app.boot()
        self.assertEqual(seen, [2])
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_boot_dip_not_off_off_error3(self):
        app, gpio, clock = self._app(dip1=True)
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR3)


class StateMachineTests(unittest.TestCase, AppHelpers):
    def test_ready_green(self):
        app, gpio, clock = self._app()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("green"))
        self.assertFalse(app.leds.physical_on("red"))

    def test_error1_red(self):
        app, gpio, clock = self._app()
        app._enter_error1(RuntimeError("boom"), state="TEST", reader_op="x")
        app.leds.tick(clock.t)
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR1)
        self.assertTrue(app.leds.physical_on("red"))
        self.assertFalse(app.leds.physical_on("green"))

    def test_error2_and_hotplug(self):
        reader = AbsentReader()
        app, gpio, clock = self._app(reader=reader)
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        app.leds.tick(clock.t)
        # Both green and red slow — at t=0 both ON
        self.assertTrue(app.leds.physical_on("green"))
        self.assertTrue(app.leds.physical_on("red"))
        reader.force_present = ReaderPresence(
            present=True, port="/dev/ttyACM0", version="ok"
        )
        clock.advance(1.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_error3_pattern_and_recovery(self):
        app, gpio, clock = self._app()
        gpio.set_input(self.DIP2, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR3)
        self.assertEqual(
            app.leds.engine.get_kind("red"), PatternKind.ERROR3
        )
        gpio.set_input(self.DIP2, True)  # OFF (pull-up high)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

    def test_wlan_heartbeat(self):
        app, gpio, clock = self._app()
        app.runtime.wlan = WlanStatus.CONNECTED
        app._apply_wlan_led()
        self.assertEqual(app.leds.engine.get_kind("blue"), PatternKind.HEARTBEAT)
        app.runtime.wlan = WlanStatus.OFFLINE
        app._apply_wlan_led()
        self.assertEqual(app.leds.engine.get_kind("blue"), PatternKind.OFF)


class SweetPModeTests(unittest.TestCase, AppHelpers):
    def test_dip1_enters_sweetp_start_ignored(self):
        app, gpio, clock = self._app()
        gpio.set_input(self.DIP1, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
        self.assertFalse(app.collector.is_running())

    def test_sweetp_leds_by_score(self):
        sweet = MockSweetPoint(period_seconds=1000)
        app, gpio, clock = self._app(sweet=sweet)
        gpio.set_input(self.DIP1, False)
        app.tick()
        cases = [
            (100, True, True, False, False),
            (75, True, True, False, False),
            (74, True, False, True, False),
            (56, True, False, True, False),
            (55, True, False, None, None),  # alternate
            (39, True, False, False, True),
            (None, False, False, False, False),
        ]
        for score, tag, g, y, r in cases:
            sweet.force(score, has_tag=tag)
            app.tick()
            app.leds.tick(clock.t)
            if y is None:
                # borderline — yellow PHASE_A / red PHASE_B
                self.assertEqual(
                    app.leds.engine.get_kind("yellow"), PatternKind.PHASE_A
                )
                self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.PHASE_B)
            else:
                self.assertEqual(app.leds.physical_on("green"), g)
                self.assertEqual(app.leds.physical_on("yellow"), y)
                self.assertEqual(app.leds.physical_on("red"), r)

    def test_leave_sweetp_to_ready(self):
        app, gpio, clock = self._app()
        gpio.set_input(self.DIP1, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
        gpio.set_input(self.DIP1, True)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)


class PositioningTests(unittest.TestCase, AppHelpers):
    def test_start_positioning_and_second_start_gate(self):
        sweet = MockSweetPoint(period_seconds=1000)
        app, gpio, clock = self._app(sweet=sweet)
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.POSITIONING)

        sweet.force(50, has_tag=True)
        app.tick()
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.POSITIONING)
        self.assertFalse(app.collector.is_running())

        sweet.force(60, has_tag=True)
        app.tick()
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.READ)
        self.assertTrue(app.collector.is_running())

    def test_positioning_leds(self):
        sweet = MockSweetPoint(period_seconds=1000)
        app, gpio, clock = self._app(sweet=sweet)
        self._pulse(gpio, app, clock, self.START)
        sweet.force(75, has_tag=True)
        app.tick()
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("green"))
        sweet.force(60, has_tag=True)
        app.tick()
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("yellow"))
        sweet.force(50, has_tag=True)
        app.tick()
        self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.PHASE_A)
        sweet.force(30, has_tag=True)
        app.tick()
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("red"))


class ReadProgressTests(unittest.TestCase, AppHelpers):
    def test_six_step_progress_and_save_ready(self):
        app, gpio, clock = self._app()
        sweet = app.sweet_point
        assert isinstance(sweet, MockSweetPoint)

        self._pulse(gpio, app, clock, self.START)
        sweet.force(80, has_tag=True)
        app.tick()
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.READ)

        expected = [
            (1, PatternKind.FAST, PatternKind.OFF, PatternKind.OFF),
            (2, PatternKind.ON, PatternKind.OFF, PatternKind.OFF),
            (3, PatternKind.ON, PatternKind.FAST, PatternKind.OFF),
            (4, PatternKind.ON, PatternKind.ON, PatternKind.OFF),
            (5, PatternKind.ON, PatternKind.ON, PatternKind.FAST),
            (6, PatternKind.ON, PatternKind.ON, PatternKind.ON),
        ]
        for step, g, y, r in expected:
            while app.runtime.read_step < step and app.collector.is_running():
                clock.advance(0.05)
                app.tick()
            if app.runtime.device_state == DeviceState.READ:
                self.assertEqual(app.leds.engine.get_kind("green"), g)
                self.assertEqual(app.leds.engine.get_kind("yellow"), y)
                self.assertEqual(app.leds.engine.get_kind("red"), r)

        while app.runtime.device_state == DeviceState.READ:
            clock.advance(0.05)
            app.tick()
        self.assertIn(
            app.runtime.device_state,
            (
                DeviceState.READ_COMPLETE,
                DeviceState.SAVE,
                DeviceState.READY,
            ),
        )
        for _ in range(250):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        app.leds.tick(clock.t)
        self.assertTrue(app.leds.physical_on("green"))

    def test_stop_during_positioning(self):
        app, gpio, clock = self._app()
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.POSITIONING)
        self._pulse(gpio, app, clock, self.STOP)
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.READY:
                break
        self.assertEqual(app.runtime.device_state, DeviceState.READY)


class GpioTestCliTests(unittest.TestCase):
    def test_gpio_test_mock(self):
        code = run_gpio_test(
            {"gpio_prefer_mock": True, "self_test": {"led_ms": 5, "cycles": 1}},
            wait_buttons=True,
            button_timeout_s=1.0,
            sleep=lambda _d: None,
        )
        self.assertEqual(code, 0)


class ReaderHotplugTests(unittest.TestCase, AppHelpers):
    def test_disconnect_ready(self):
        reader = ToggleableReader()
        app, gpio, clock = self._app(reader=reader)
        self.assertEqual(app.runtime.device_state, DeviceState.READY)
        reader.present = False
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)

    def test_disconnect_sweetp(self):
        reader = ToggleableReader()
        app, gpio, clock = self._app(reader=reader)
        gpio.set_input(self.DIP1, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
        reader.present = False
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        self.assertFalse(app.sweet_point.is_running())

    def test_disconnect_positioning(self):
        reader = ToggleableReader()
        app, gpio, clock = self._app(reader=reader)
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.POSITIONING)
        reader.present = False
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        self.assertFalse(app.sweet_point.is_running())

    def test_disconnect_during_read(self):
        reader = ToggleableReader()
        sweet = MockSweetPoint(period_seconds=1000)
        app, gpio, clock = self._app(reader=reader, sweet=sweet)
        self._pulse(gpio, app, clock, self.START)
        sweet.force(80, has_tag=True)
        app.tick()
        self._pulse(gpio, app, clock, self.START)
        self.assertEqual(app.runtime.device_state, DeviceState.READ)
        self.assertTrue(app.collector.is_running())
        reader.present = False
        app.tick()
        # Cooperative stop in progress; drain to ERROR2
        for _ in range(40):
            clock.advance(0.05)
            app.tick()
            if app.runtime.device_state == DeviceState.ERROR2:
                break
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        self.assertTrue(app._reader_lost_during_capture is False)
        self.assertFalse(app.collector.is_running())

    def test_reconnect_recovery_ready_and_sweetp(self):
        reader = ToggleableReader()
        app, gpio, clock = self._app(reader=reader)
        reader.present = False
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        reader.present = True
        clock.advance(1.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.READY)

        gpio.set_input(self.DIP1, False)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)
        reader.present = False
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.ERROR2)
        reader.present = True
        clock.advance(1.1)
        app.tick()
        self.assertEqual(app.runtime.device_state, DeviceState.SWEETP)


class RuntimeCwdTests(unittest.TestCase):
    def test_ensure_runtime_cwd_changes_directory(self):
        import os

        from hwsniff.runtime import ensure_runtime_cwd

        with tempfile.TemporaryDirectory() as tmp:
            before = os.getcwd()
            try:
                path = ensure_runtime_cwd({"data_root": tmp})
                self.assertEqual(path, Path(tmp))
                self.assertEqual(Path(os.getcwd()), Path(tmp))
            finally:
                os.chdir(before)


if __name__ == "__main__":
    unittest.main()
