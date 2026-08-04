"""Unit tests for SweetP cycle stats and snapshot handoff."""

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
from hwsniff.sweetp_stats import SweetPCycleStats, SweetPSnapshot


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class AlwaysPresentReader(ReaderMonitor):
    def __init__(self, port: str = "/dev/ttyS0") -> None:
        self._presence = ReaderPresence(present=True, port=port, version="TWN4")

    def tick(self, now=None, *, force: bool = False):
        return self._presence

    def probe(self):
        return self._presence


class SweetPStatsUnitTests(unittest.TestCase):
    def test_ignores_none_and_no_tag(self):
        stats = SweetPCycleStats()
        stats.add_sample(None, has_tag=False)
        stats.add_sample(50.0, has_tag=False)
        stats.add_sample(None, has_tag=True)
        snap = stats.freeze(score_at_accept=60.0, band_at_accept="usable")
        self.assertEqual(snap.sample_count, 0)
        self.assertEqual(snap.score_at_accept, 60.0)
        self.assertIsNone(snap.minimum)

    def test_min_max_average(self):
        stats = SweetPCycleStats()
        for v in (10.0, 20.0, 30.0):
            stats.add_sample(v, has_tag=True)
        snap = stats.freeze(score_at_accept=30.0, band_at_accept="bad")
        self.assertEqual(snap.minimum, 10.0)
        self.assertEqual(snap.maximum, 30.0)
        self.assertEqual(snap.average, 20.0)
        self.assertEqual(snap.sample_count, 3)

    def test_reset_clears_cycle(self):
        stats = SweetPCycleStats()
        stats.add_sample(40.0, has_tag=True)
        stats.reset()
        stats.add_sample(80.0, has_tag=True)
        snap = stats.freeze(score_at_accept=80.0, band_at_accept="good")
        self.assertEqual(snap.sample_count, 1)
        self.assertEqual(snap.minimum, 80.0)

    def test_freeze_is_immutable(self):
        stats = SweetPCycleStats()
        stats.add_sample(50.0, has_tag=True)
        first = stats.freeze(score_at_accept=50.0, band_at_accept="borderline")
        stats.add_sample(99.0, has_tag=True)
        second = stats.freeze(score_at_accept=1.0, band_at_accept="bad")
        self.assertIs(first, second)
        self.assertEqual(second.sample_count, 1)
        self.assertEqual(second.score_at_accept, 50.0)


class SweetPStatsAppTests(unittest.TestCase):
    START = 21

    def _app(self, tmp: str):
        gpio = MockGpioBackend()
        clock = Clock()
        coll = MockCollector(
            work_seconds=0.5,
            save_seconds=0.05,
            phase_seconds=0.05,
            outcome=CollectorOutcome.SUCCESS,
            clock=clock,
        )
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
        return app, gpio, clock, coll, sweet

    def _pulse(self, gpio, app, clock, pin: int):
        gpio.press_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()
        gpio.release_active_low(pin)
        app.tick()
        clock.advance(0.06)
        app.tick()

    def test_snapshot_passed_to_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, coll, sweet = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            self.assertEqual(app.runtime.device_state, DeviceState.POSITIONING)
            sweet.force(70.0, has_tag=True)
            for _ in range(3):
                clock.advance(0.05)
                app.tick()
            sweet.force(78.5, has_tag=True)
            app.tick()
            self._pulse(gpio, app, clock, self.START)
            self.assertEqual(app.runtime.device_state, DeviceState.READ)
            self.assertIsNotNone(coll.summary_extra)
            sweetp = coll.summary_extra["sweetp"]
            self.assertAlmostEqual(sweetp["score_at_accept"], 78.5)
            self.assertEqual(sweetp["band_at_accept"], "good")
            self.assertGreaterEqual(sweetp["sample_count"], 1)
            self.assertIsInstance(
                app._sweetp_snapshot, SweetPSnapshot
            )
            # Frozen — later samples must not change snapshot
            before = dict(sweetp)
            app._sweetp_stats.add_sample(1.0, has_tag=True)
            self.assertEqual(app._sweetp_snapshot.to_dict(), before)

    def test_new_positioning_resets_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, gpio, clock, coll, sweet = self._app(tmp)
            self._pulse(gpio, app, clock, self.START)
            sweet.force(40.0, has_tag=True)
            app.tick()
            self._pulse(gpio, app, clock, 6)
            for _ in range(40):
                clock.advance(0.05)
                app.tick()
                if app.runtime.device_state == DeviceState.READY:
                    break
            self.assertEqual(app.runtime.device_state, DeviceState.READY)
            self._pulse(gpio, app, clock, self.START)
            sweet.force(80.0, has_tag=True)
            app.tick()
            self._pulse(gpio, app, clock, self.START)
            self.assertIsNotNone(coll.summary_extra)
            sweetp = coll.summary_extra["sweetp"]
            self.assertEqual(sweetp["minimum"], 80.0)
            self.assertNotIn(40.0, [sweetp["minimum"], sweetp["maximum"]])


if __name__ == "__main__":
    unittest.main()
