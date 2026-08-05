"""Unit tests for continuous SweetP LED meter."""

from __future__ import annotations

import unittest

from hwsniff.patterns import PatternKind
from hwsniff.sweetp_leds import plan_sweetp_leds


class SweetPLedPlanTests(unittest.TestCase):
    def test_no_tag_fast_red(self):
        plan = plan_sweetp_leds(None, has_tag=False)
        self.assertEqual(plan.red, PatternKind.PERIODIC_PULSE)
        self.assertEqual(plan.green, PatternKind.OFF)
        self.assertEqual(plan.yellow, PatternKind.OFF)
        self.assertLessEqual(plan.red_period_ms or 999, 200)

    def test_weak_red_slows_with_score(self):
        weak = plan_sweetp_leds(10.0, has_tag=True)
        better = plan_sweetp_leds(35.0, has_tag=True)
        self.assertEqual(weak.red, PatternKind.PERIODIC_PULSE)
        self.assertEqual(better.red, PatternKind.PERIODIC_PULSE)
        self.assertGreater(better.red_period_ms or 0, weak.red_period_ms or 0)
        self.assertEqual(better.yellow, PatternKind.PERIODIC_PULSE)

    def test_usable_no_red_yellow_and_green(self):
        low = plan_sweetp_leds(58.0, has_tag=True)
        high = plan_sweetp_leds(72.0, has_tag=True)
        self.assertEqual(low.red, PatternKind.OFF)
        self.assertEqual(low.yellow, PatternKind.PERIODIC_PULSE)
        self.assertEqual(low.green, PatternKind.PERIODIC_PULSE)
        self.assertGreater(high.yellow_period_ms or 0, low.yellow_period_ms or 0)
        self.assertLess(high.green_period_ms or 999, low.green_period_ms or 0)

    def test_good_solid_green(self):
        plan = plan_sweetp_leds(80.0, has_tag=True)
        self.assertEqual(plan.green, PatternKind.ON)
        self.assertEqual(plan.yellow, PatternKind.OFF)
        self.assertEqual(plan.red, PatternKind.OFF)
