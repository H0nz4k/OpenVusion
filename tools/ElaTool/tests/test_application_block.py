from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.analysis.application_block import (
    CONFIRMED_LE_PAGE_33,
    analyze_application_block,
    analyze_application_block_file,
    compare_application_blocks,
)
from elatec_uid_tool.analysis.checksums import evaluate_checksum_candidates
from elatec_uid_tool.cli import build_parser
from elatec_uid_tool.ntag import EEPROM_WATCH_SIZE_BYTES


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF"
    "FF FF FF FF"
    "FF FF FF FF"
    "C9 D0 2C AA"
    "FF 3A 10 00"
    "00 33 00 02"
    "01 0D 02 02"
    "D5 01 6C 93"
)


class ApplicationBlockTests(unittest.TestCase):
    def test_exact_32_bytes_and_mapping(self):
        report = analyze_application_block(REFERENCE_BLOCK, source="test")
        self.assertEqual(len(report.block), EEPROM_WATCH_SIZE_BYTES)
        self.assertEqual(report.pages[0x30], bytes.fromhex("A0 81 FF FF"))
        self.assertEqual(report.pages[0x33], CONFIRMED_LE_PAGE_33)
        data = report.to_dict()
        self.assertEqual(data["bytes"][0]["page"], 0x30)
        self.assertEqual(data["bytes"][12]["page"], 0x33)

    def test_short_input_rejected(self):
        with self.assertRaises(ValueError):
            analyze_application_block(b"\x00" * 31)

    def test_confirmed_little_endian_match(self):
        report = analyze_application_block(REFERENCE_BLOCK)
        data = report.to_dict()
        self.assertTrue(data["ndef_id"]["confirmed_little_endian_identifier_match"])
        self.assertTrue(
            any("confirmed little-endian identifier match" in fact for fact in report.facts)
        )

    def test_endian_views(self):
        data = analyze_application_block(REFERENCE_BLOCK).to_dict()
        page33 = next(item for item in data["endian_views"]["u32"] if item["page"] == 0x33)
        self.assertEqual(page33["le"], 0xAA2CD0C9)
        self.assertEqual(page33["be"], 0xC9D02CAA)

    def test_checksum_serialization(self):
        candidates = evaluate_checksum_candidates(REFERENCE_BLOCK)
        self.assertGreater(len(candidates), 0)
        matches = [item for item in candidates if item.matches]
        # Matches are candidates only; presence is fine, absence also fine.
        report = analyze_application_block(REFERENCE_BLOCK).to_dict()
        self.assertIn("checksum_matches", report)
        self.assertEqual(
            report["checksum_candidates_total"],
            len(candidates),
        )
        self.assertEqual(len(report["checksum_matches"]), len(matches))

    def test_compare_constant_and_variable(self):
        other = bytearray(REFERENCE_BLOCK)
        other[20] = 0x44  # page 0x35
        comparison = compare_application_blocks(
            [("a", REFERENCE_BLOCK), ("b", bytes(other))]
        )
        self.assertIn(20, comparison.variable_offsets)
        self.assertNotIn(12, comparison.variable_offsets)  # ID constant
        self.assertTrue(comparison.ndef_id_correlation["all_equal"])
        self.assertTrue(any(item["absolute_offset"] == 20 for item in comparison.byte_changes))

    def test_load_existing_dump_format(self):
        # Mimic dump_A.json decimal page keys.
        pages = {}
        for page in range(0x30, 0x38):
            offset = (page - 0x30) * 4
            pages[f"{page:03d}"] = REFERENCE_BLOCK[offset : offset + 4].hex(" ").upper()
        document = {"uid": "04367F5A2D7280", "pages": pages}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dump.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            report = analyze_application_block_file(path)
            self.assertEqual(report.block, REFERENCE_BLOCK)
            self.assertEqual(report.uid, "04367F5A2D7280")

    def test_cli_parsers(self):
        parser = build_parser()
        args = parser.parse_args(["application-block", "--port", "COM6"])
        self.assertEqual(args.command, "application-block")
        args2 = parser.parse_args(["analyze-application-block", "x.json"])
        self.assertEqual(args2.dump, "x.json")
        args3 = parser.parse_args(
            ["compare-application-blocks", "a.json", "b.json"]
        )
        self.assertEqual(args3.dumps, ["a.json", "b.json"])


if __name__ == "__main__":
    unittest.main()
