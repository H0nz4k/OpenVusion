"""Dual-score SweetP filter, trend LEDs, trace, READ uses stable score."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hwsniff.app import HeadlessApp
from hwsniff.buttons import ButtonEvent
from hwsniff.collector_service import MockCollector
from hwsniff.configuration import DEFAULT_CONFIG, deep_merge
from hwsniff.gpio_backend import MockGpioBackend
from hwsniff.network import NetworkMonitor
from hwsniff.patterns import PatternKind
from hwsniff.reader_monitor import ReaderMonitor, ReaderPresence
from hwsniff.state import CollectorOutcome, DeviceState, SweetBand
from hwsniff.sweet_point import MockSweetPoint
from hwsniff.sweetp_bands import score_allows_read
from hwsniff.sweetp_filter import SweetPDualFilter, SweetPFilterConfig, filter_config_from_sweet
from hwsniff.sweetp_stats import SweetPCycleStats


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


class FilterUnitTests(unittest.TestCase):
    def test_fast_from_first_sample_stable_slower(self):
        f = SweetPDualFilter(
            SweetPFilterConfig(fast_alpha=0.7, stable_alpha=0.2, trend_window_samples=3)
        )
        t0 = f.update(20.0, has_tag=True, now=0.0)
        self.assertEqual(t0.fast_score, 20.0)
        self.assertEqual(t0.stable_score, 20.0)
        t1 = f.update(80.0, has_tag=True, now=0.5)
        self.assertGreater(t1.fast_score, t1.stable_score)
        self.assertAlmostEqual(t1.fast_score, 0.7 * 80 + 0.3 * 20)
        self.assertAlmostEqual(t1.stable_score, 0.2 * 80 + 0.8 * 20)

    def test_deadband_suppresses_blink(self):
        f = SweetPDualFilter(
            SweetPFilterConfig(
                fast_alpha=1.0,
                stable_alpha=1.0,
                trend_window_samples=2,
                trend_deadband_points_per_second=15.0,
            )
        )
        f.update(50.0, has_tag=True, now=0.0)
        tick = f.update(52.0, has_tag=True, now=1.0)  # 2 pps
        self.assertEqual(tick.trend_direction, "stable")
        self.assertIsNone(tick.blink_interval_ms)

    def test_stronger_trend_faster_blink(self):
        cfg = SweetPFilterConfig(
            fast_alpha=1.0,
            stable_alpha=1.0,
            trend_window_samples=2,
            trend_deadband_points_per_second=5.0,
            trend_strong_points_per_second=40.0,
            trend_min_blink_interval_ms=200,
            trend_max_blink_interval_ms=1000,
        )
        weak = SweetPDualFilter(cfg)
        weak.update(40.0, has_tag=True, now=0.0)
        tw = weak.update(50.0, has_tag=True, now=1.0)  # +10 pps
        strong = SweetPDualFilter(cfg)
        strong.update(40.0, has_tag=True, now=0.0)
        ts = strong.update(80.0, has_tag=True, now=1.0)  # +40 pps
        self.assertEqual(tw.trend_direction, "improving")
        self.assertEqual(ts.trend_direction, "improving")
        self.assertLess(ts.blink_interval_ms, tw.blink_interval_ms)

    def test_isolated_none_no_strong_negative(self):
        f = SweetPDualFilter(
            SweetPFilterConfig(no_tag_confirm_samples=2, fast_alpha=1.0, stable_alpha=1.0)
        )
        f.update(70.0, has_tag=True, now=0.0)
        f.update(72.0, has_tag=True, now=0.5)
        miss = f.update(None, has_tag=False, now=1.0)
        self.assertTrue(miss.fast_score is not None)  # not yet confirmed lost
        self.assertNotEqual(miss.trend_direction, "worsening")

    def test_legacy_config_defaults(self):
        cfg = filter_config_from_sweet({})
        self.assertAlmostEqual(cfg.fast_alpha, 0.60)
        self.assertAlmostEqual(cfg.stable_alpha, 0.20)
        self.assertIn("fast_alpha", DEFAULT_CONFIG["sweetp"])


class AppTrendTests(unittest.TestCase):
    START = 21
    STOP = 6

    def _app(self, tmp: str):
        gpio = MockGpioBackend()
        clock = Clock()
        sweet = MockSweetPoint(
            period_seconds=1000,
            clock=clock,
            filter_cfg=SweetPFilterConfig(
                fast_alpha=0.8,
                stable_alpha=0.15,
                trend_window_samples=3,
                trend_deadband_points_per_second=5.0,
                trend_strong_points_per_second=40.0,
                trend_min_blink_interval_ms=200,
                trend_max_blink_interval_ms=1000,
                trend_pulse_ms=80,
            ),
        )
        coll = MockCollector(
            work_seconds=0.4,
            save_seconds=0.05,
            phase_seconds=0.05,
            outcome=CollectorOutcome.SUCCESS,
            clock=clock,
        )
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
            },
            gpio=gpio,
            collector=coll,
            sweet_point=sweet,
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
        return app, gpio, clock, sweet, coll

    def _pulse(self, gpio, app, clock, pin):
        gpio.press_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()

    def test_read_uses_stable_not_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            # Jump raw high so fast >> stable early
            sweet.push_raw(30.0, has_tag=True, advance=0.0)
            app.tick()
            sweet.push_raw(90.0, has_tag=True, advance=0.4)
            app.tick()
            self.assertIsNotNone(sweet.get_sample().fast_score)
            self.assertIsNotNone(sweet.get_sample().score)
            self.assertGreater(sweet.get_sample().fast_score, sweet.get_sample().score)
            # READ gate uses stable
            allowed_fast = score_allows_read(
                sweet.get_sample().fast_score, has_tag=True
            )
            allowed_stable = score_allows_read(
                sweet.get_sample().score, has_tag=True
            )
            self.assertTrue(allowed_fast)
            # Keep feeding until stable crosses read_minimum
            for _ in range(20):
                sweet.push_raw(90.0, has_tag=True, advance=0.3)
                app.tick()
                if score_allows_read(app.runtime.sweet_score, has_tag=True):
                    break
            self.assertTrue(score_allows_read(app.runtime.sweet_score, has_tag=True))
            self._pulse(gpio, app, clock, self.START)
            self.assertEqual(app.runtime.device_state, DeviceState.READ)
            self.assertAlmostEqual(
                coll.summary_extra["sweetp"]["score_at_accept"],
                app._sweetp_snapshot.score_at_accept,
            )

    def test_improving_green_overlay_on_yellow(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, _coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            for v in (58.0, 60.0, 62.0, 64.0):
                sweet.push_raw(v, has_tag=True, advance=0.35)
                app.tick()
            self.assertIn(
                app.runtime.sweet_band, (SweetBand.USABLE, SweetBand.GOOD)
            )
            # Force usable base + strong improve
            while app.runtime.sweet_band != SweetBand.USABLE:
                sweet.push_raw(60.0, has_tag=True, advance=0.35)
                app.tick()
                if clock.t > 20:
                    break
            sweet.push_raw(90.0, has_tag=True, advance=0.5)
            app.tick()
            self.assertEqual(app.leds.engine.get_kind("yellow"), PatternKind.ON)
            self.assertEqual(
                app.leds.engine.get_kind("green"), PatternKind.PERIODIC_PULSE
            )
            ch = app.leds.engine._channels["green"]
            self.assertIsNotNone(ch.period_ms)
            self.assertLessEqual(ch.period_ms, 1000)

    def test_worsening_red_overlay_on_yellow(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, _coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            for v in (70.0, 68.0, 66.0, 64.0):
                sweet.push_raw(v, has_tag=True, advance=0.35)
                app.tick()
            while app.runtime.sweet_band not in (SweetBand.USABLE, SweetBand.GOOD):
                sweet.push_raw(65.0, has_tag=True, advance=0.35)
                app.tick()
                if clock.t > 20:
                    break
            # Drop sharply while keeping yellow-ish stable if possible
            sweet.push_raw(40.0, has_tag=True, advance=0.5)
            app.tick()
            self.assertEqual(
                app.leds.engine.get_kind("red"), PatternKind.PERIODIC_PULSE
            )

    def test_collision_bad_worsening_stays_solid_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, _coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            sweet.push_raw(20.0, has_tag=True, advance=0.0)
            app.tick()
            sweet.push_raw(5.0, has_tag=True, advance=0.5)
            app.tick()
            self.assertEqual(app.runtime.sweet_band, SweetBand.BAD)
            self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.ON)
            self.assertEqual(app.leds.engine.get_kind("green"), PatternKind.OFF)

    def test_cycle_reset_clears_trace(self):
        stats = SweetPCycleStats()
        stats.add_sample(40.0, has_tag=True, trace_row={"seq": 1, "stable_score": 40})
        stats.reset(filter_config={"fast_alpha": 0.6})
        stats.add_sample(80.0, has_tag=True, trace_row={"seq": 1, "stable_score": 80})
        snap = stats.freeze(score_at_accept=80.0, band_at_accept="good")
        self.assertEqual(snap.sample_count, 1)
        self.assertEqual(snap.minimum, 80.0)
        self.assertIn("fast_alpha", snap.filter_config)

    def test_trace_jsonl_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            for v in (60.0, 70.0, 80.0):
                sweet.push_raw(v, has_tag=True, advance=0.4)
                app.tick()
            self._pulse(gpio, app, clock, self.START)
            self.assertEqual(app.runtime.device_state, DeviceState.READ)
            self.assertIn("sweetp_trace.jsonl", coll.artifact_files or {})
            text = coll.artifact_files["sweetp_trace.jsonl"]
            lines = [ln for ln in text.strip().splitlines() if ln]
            self.assertGreaterEqual(len(lines), 2)
            row = json.loads(lines[0])
            self.assertIn("raw_score", row)
            self.assertIn("fast_score", row)
            self.assertIn("stable_score", row)
            self.assertTrue(any(json.loads(ln).get("accepted") for ln in lines))

    def test_overlay_cleared_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, _coll = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            sweet.push_raw(50.0, has_tag=True, advance=0.0)
            app.tick()
            sweet.push_raw(75.0, has_tag=True, advance=0.5)
            app.tick()
            self.assertTrue(app._sweet_trend_active)
            for _ in range(15):
                sweet.push_raw(80.0, has_tag=True, advance=0.3)
                app.tick()
            self._pulse(gpio, app, clock, self.START)
            self.assertEqual(app.runtime.device_state, DeviceState.READ)
            self.assertFalse(app._sweet_trend_active)

    def test_chord_priority_over_sweet_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, sweet, _coll = self._app(tmp)
            # tighten chord in buttons config already default 5s — use direct path
            self._pulse(gpio, app, clock, self.START)
            sweet.push_raw(55.0, has_tag=True, advance=0.0)
            app.tick()
            sweet.push_raw(70.0, has_tag=True, advance=0.5)
            app.tick()
            gpio.set_input(self.START, False)
            gpio.set_input(self.STOP, False)
            clock.advance(0.06)
            app.tick()
            clock.advance(0.06)
            app.tick()
            t_arm = clock.t
            while clock.t < t_arm + 4.2:
                clock.advance(0.1)
                app.tick()
            self.assertTrue(app._chord_warning_active)
            self.assertEqual(app.leds.engine.get_kind("red"), PatternKind.COUNT_BLINK)


if __name__ == "__main__":
    unittest.main()
