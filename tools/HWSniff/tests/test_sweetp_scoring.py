from __future__ import annotations

import unittest

from hwsniff.legacy.sweetp_scoring import (
    ScoringConfig,
    SweetPSample,
    SweetPScorer,
    SweetPTrend,
    latency_score,
    quality_from_window,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def sample(ok: bool, uid: str | None, latency: float, ts: float) -> SweetPSample:
    return SweetPSample(success=ok, uid=uid, latency_ms=latency, monotonic_ts=ts)


class ScoringUnitTests(unittest.TestCase):
    def test_latency_score_bounds(self):
        self.assertEqual(latency_score(50, 80, 600), 1.0)
        self.assertEqual(latency_score(600, 80, 600), 0.0)
        self.assertAlmostEqual(latency_score(340, 80, 600), 0.5, places=2)

    def test_20_successes_high_score(self):
        samples = [sample(True, "A", 60, i) for i in range(20)]
        cfg = ScoringConfig(use_latency=True)
        q, sr, uid_c, dom, avg = quality_from_window(samples, cfg)
        self.assertGreaterEqual(q, 90)
        self.assertEqual(sr, 1.0)
        self.assertEqual(dom, "A")
        self.assertEqual(uid_c, 1.0)
        self.assertIsNotNone(avg)

    def test_failures_lower_score(self):
        samples = [sample(True, "A", 60, i) for i in range(10)]
        samples += [sample(False, None, 500, i + 10) for i in range(10)]
        cfg = ScoringConfig(use_latency=True)
        q, sr, *_ = quality_from_window(samples, cfg)
        self.assertLess(q, 70)
        self.assertEqual(sr, 0.5)

    def test_alternating_uid_lowers_consistency(self):
        samples = []
        for i in range(20):
            uid = "A" if i % 2 == 0 else "B"
            samples.append(sample(True, uid, 70, i))
        cfg = ScoringConfig(use_latency=False)
        q, _sr, uid_c, *_ = quality_from_window(samples, cfg)
        self.assertLessEqual(uid_c, 0.55)
        self.assertLess(q, 95)

    def test_faster_latency_better_than_slow(self):
        cfg = ScoringConfig(use_latency=True)
        fast = [sample(True, "A", 50, i) for i in range(20)]
        slow = [sample(True, "A", 500, i) for i in range(20)]
        q_fast, *_ = quality_from_window(fast, cfg)
        q_slow, *_ = quality_from_window(slow, cfg)
        self.assertGreater(q_fast, q_slow)

    def test_single_good_sample_not_position_ok(self):
        clock = FakeClock()
        scorer = SweetPScorer(
            ScoringConfig(good_hold_ms=3000, min_samples_for_ok=8),
            clock=clock,
        )
        snap = scorer.add_sample(sample(True, "A", 50, clock()))
        self.assertFalse(snap.position_ok)

    def test_position_ok_requires_hold(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            good_quality_threshold=85,
            good_hold_ms=3000,
            min_samples_for_ok=5,
            window_size=20,
            use_latency=True,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        for i in range(10):
            scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.1)
        snap = scorer.snapshot()
        self.assertFalse(snap.position_ok)
        clock.advance(3.1)
        # Re-evaluate by adding another good sample after hold window.
        snap = scorer.add_sample(sample(True, "A", 50, clock()))
        self.assertTrue(snap.position_ok)

    def test_position_ok_lost_on_drop(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            good_quality_threshold=85,
            good_hold_ms=1000,
            min_samples_for_ok=5,
            window_size=10,
            use_latency=False,
            weight_success=0.8,
            weight_latency=0.0,
            weight_uid_consistency=0.2,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        for _ in range(8):
            scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.2)
        clock.advance(1.2)
        snap = scorer.add_sample(sample(True, "A", 50, clock()))
        self.assertTrue(snap.position_ok)
        for _ in range(10):
            snap = scorer.add_sample(sample(False, None, 400, clock()))
            clock.advance(0.1)
        self.assertFalse(snap.position_ok)

    def test_trend_improving(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            window_size=20,
            short_window_size=5,
            min_samples_for_trend=5,
            trend_threshold=5,
            trend_hold_ms=0,
            use_latency=False,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        # Poor first half
        for _ in range(10):
            scorer.add_sample(sample(False, None, 400, clock()))
            clock.advance(0.05)
        # Strong second half
        for _ in range(10):
            snap = scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.05)
        self.assertEqual(snap.trend, SweetPTrend.IMPROVING)

    def test_trend_worsening(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            window_size=20,
            short_window_size=5,
            min_samples_for_trend=5,
            trend_threshold=5,
            trend_hold_ms=0,
            use_latency=False,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        for _ in range(10):
            scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.05)
        for _ in range(10):
            snap = scorer.add_sample(sample(False, None, 400, clock()))
            clock.advance(0.05)
        self.assertEqual(snap.trend, SweetPTrend.WORSENING)

    def test_small_change_stays_stable(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            window_size=20,
            short_window_size=5,
            min_samples_for_trend=5,
            trend_threshold=5,
            trend_hold_ms=0,
            use_latency=True,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        for i in range(20):
            # All successes; only tiny latency jitter (±10 ms).
            latency = 70 + (i % 3) * 5
            snap = scorer.add_sample(sample(True, "A", latency, clock()))
            clock.advance(0.05)
        self.assertEqual(snap.trend, SweetPTrend.STABLE)

    def test_trend_hysteresis(self):
        clock = FakeClock()
        cfg = ScoringConfig(
            window_size=20,
            short_window_size=5,
            min_samples_for_trend=5,
            trend_threshold=5,
            trend_hold_ms=1000,
            use_latency=False,
        )
        scorer = SweetPScorer(cfg, clock=clock)
        for _ in range(10):
            scorer.add_sample(sample(False, None, 400, clock()))
            clock.advance(0.05)
        # Improve but hold not elapsed enough for first improving samples
        for _ in range(5):
            snap = scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.05)
        # Still within hold from initial STABLE stamp — may still be STABLE
        early = snap.trend
        clock.advance(1.2)
        for _ in range(5):
            snap = scorer.add_sample(sample(True, "A", 50, clock()))
            clock.advance(0.05)
        self.assertEqual(snap.trend, SweetPTrend.IMPROVING)
        self.assertIn(early, (SweetPTrend.STABLE, SweetPTrend.IMPROVING))


if __name__ == "__main__":
    unittest.main()
