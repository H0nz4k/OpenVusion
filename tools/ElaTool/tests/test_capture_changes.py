import unittest

from elatec_uid_tool.capture.changes import (
    changed_bits,
    changed_ranges,
    eeprom_changes,
    session_changes,
    sram_changes,
    byte_changes,
)
from elatec_uid_tool.capture.models import safe_ascii_preview


class SessionChangeTests(unittest.TestCase):
    def test_detect_session_register_and_bit_changes(self):
        previous = bytes.fromhex("19 00 F8 48 08 01 01 00")
        current = bytes.fromhex("7C 00 F8 48 08 01 29 00")

        result = session_changes(previous, current)

        self.assertTrue(result["changed"])
        names = [item["name"] for item in result["registers"]]
        self.assertEqual(names, ["NC_REG", "NS_REG"])

        nc = result["registers"][0]
        self.assertEqual(nc["old"], 0x19)
        self.assertEqual(nc["new"], 0x7C)
        self.assertIn(2, nc["changed_bits"])
        self.assertIn(6, nc["changed_bits"])

        ns = result["registers"][1]
        self.assertEqual(ns["changed_bits"], changed_bits(0x01, 0x29))

    def test_no_session_change(self):
        data = bytes.fromhex("19 00 F8 48 08 01 01 00")
        result = session_changes(data, data)
        self.assertFalse(result["changed"])
        self.assertEqual(result["registers"], [])


class SramChangeTests(unittest.TestCase):
    def test_detect_offsets_and_ranges(self):
        previous = bytes(64)
        current = bytearray(64)
        current[10] = 0xAA
        current[11] = 0xBB
        current[20] = 0xCC

        result = sram_changes(previous, bytes(current))

        self.assertTrue(result["changed"])
        self.assertEqual(result["offsets"], [10, 11, 20])
        self.assertEqual(
            result["ranges"],
            [{"start": 10, "end": 11}, {"start": 20, "end": 20}],
        )

    def test_zero_sram_is_not_missing(self):
        zeros = bytes(64)
        result = sram_changes(zeros, zeros)
        self.assertFalse(result["changed"])
        self.assertEqual(result["current_hex"], zeros.hex(" ").upper())

    def test_changed_ranges_helper(self):
        changes = byte_changes(bytes([0, 0, 0, 0]), bytes([1, 1, 0, 2]))
        ranges = changed_ranges(changes)
        self.assertEqual([(item.start, item.end) for item in ranges], [(0, 1), (3, 3)])


class EepromChangeTests(unittest.TestCase):
    def test_page_and_byte_diff(self):
        previous = bytes.fromhex(
            "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
            "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
        )
        current = bytearray(previous)
        current[12] = 0x00  # page 0x33 byte 0

        result = eeprom_changes(previous, bytes(current), start_page=0x30)
        self.assertTrue(result["changed"])
        self.assertEqual(result["pages"][0]["page"], 0x33)
        self.assertEqual(result["bytes"][0]["page"], 0x33)


class AsciiPreviewTests(unittest.TestCase):
    def test_safe_ascii(self):
        self.assertEqual(safe_ascii_preview(b"AB\x00C"), "AB.C")


if __name__ == "__main__":
    unittest.main()
