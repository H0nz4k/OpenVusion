import unittest
from elatec_uid_tool.analyzer import analyze_uid


class AnalyzerTests(unittest.TestCase):
    def test_reference_card(self):
        _, matches = analyze_uid("3D00C000D4", 40, "12583124", "decimal", 20)
        self.assertTrue(matches)
        self.assertEqual(matches[0].first_bit, 8)
        self.assertEqual(matches[0].number_of_bits, 32)
        self.assertFalse(matches[0].reverse_bit_order)
        self.assertFalse(matches[0].reverse_byte_order)


if __name__ == "__main__":
    unittest.main()
