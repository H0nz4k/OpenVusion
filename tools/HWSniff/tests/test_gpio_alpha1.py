"""Alpha1 GPIO suite retired — see test_hwsniff_v2.py."""

from __future__ import annotations

import unittest


class Alpha1Retired(unittest.TestCase):
    def test_redirect_to_v2(self):
        self.assertTrue(True, "Use tests.test_hwsniff_v2")


if __name__ == "__main__":
    unittest.main()
