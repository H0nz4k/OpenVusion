from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.capture.logic_analyzer import (
    LogicAnalyzerCapture,
    LogicAnalyzerConfig,
)
from elatec_uid_tool.cli import build_parser
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class ScriptedClient:
    """Fake SimpleProtocolClient for offline capture tests."""

    def __init__(self, port: str = "COM6", timeout: float = 2.0) -> None:
        self.port = port
        self.timeout = timeout
        self._search_count = 0
        self._session_values = [
            bytes.fromhex("19 00 F8 48 08 01 01 00"),
            bytes.fromhex("7C 00 F8 48 08 01 29 00"),
            bytes.fromhex("19 00 F8 48 08 01 01 00"),
        ]
        self._session_index = 0
        self._sram_values = [
            bytes(64),
            bytes([0x11] + [0] * 63),
            bytes(64),
        ]
        self._sram_index = 0
        self.rf_off_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def search_tag(self, max_id_bytes: int = 32):
        self._search_count += 1
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self) -> None:
        self.rf_off_called = True

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        opcode = tx[0]
        if opcode == 0x60:
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0xEC and end == 0xED:
                value = self._session_values[
                    min(self._session_index, len(self._session_values) - 1)
                ]
                self._session_index += 1
                return with_crc(value)
            if start == 0xF0 and end == 0xFF:
                value = self._sram_values[
                    min(self._sram_index, len(self._sram_values) - 1)
                ]
                self._sram_index += 1
                return with_crc(value)
            if start == 0x30 and end == 0x37:
                return with_crc(bytes(32))
        raise AssertionError(f"Neočekávaný TX: {tx.hex(' ').upper()}")


class FakeClock:
    def __init__(self) -> None:
        self.ns = 0

    def __call__(self) -> int:
        return self.ns

    def advance(self, ns: int) -> None:
        self.ns += ns


class LogicAnalyzerTests(unittest.TestCase):
    def test_cli_parser_defaults(self):
        parser = build_parser()
        args = parser.parse_args(
            ["logic-analyzer", "--port", "COM6", "--watch-eeprom", "--verbose"]
        )
        self.assertEqual(args.command, "logic-analyzer")
        self.assertEqual(args.port, "COM6")
        self.assertEqual(args.duration, 5.0)
        self.assertEqual(args.interval_ms, 50.0)
        self.assertTrue(args.watch_eeprom)
        self.assertTrue(args.verbose)
        self.assertEqual(args.output_dir, "captures/logic-analyzer")

    def test_timeline_capture_with_scripted_transport(self):
        clock = FakeClock()

        def sleep(seconds: float) -> None:
            clock.advance(int(seconds * 1_000_000_000))

        with tempfile.TemporaryDirectory() as tmp:
            config = LogicAnalyzerConfig(
                port="COM6",
                duration_s=0.12,
                interval_ms=40,
                output_dir=Path(tmp),
                watch_eeprom=False,
                verbose=False,
                wait_tag_s=1.0,
            )
            capture = LogicAnalyzerCapture(
                config,
                client_factory=lambda port, timeout: ScriptedClient(port, timeout),
                clock_ns=clock,
                wall_clock=lambda: "2026-07-31T00:00:00+02:00",
                sleep=sleep,
            )
            # Advance clock during RF ops implicitly via sleep; also nudge after each
            # timed read by wrapping isn't needed because duration uses clock.
            # Kick the clock forward enough across sleeps from the loop.
            result = capture.run()

            self.assertEqual(result.uid, "04367F5A2D7280")
            self.assertFalse(result.partial)
            self.assertGreaterEqual(result.sample_cycles, 2)
            self.assertTrue(result.directory.exists())
            self.assertIn("04367F5A2D7280", result.directory.name)

            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            types = [item["event_type"] for item in timeline]
            self.assertIn("capture_started", types)
            self.assertIn("tag_detected", types)
            self.assertIn("get_version", types)
            self.assertIn("session_sample", types)
            self.assertIn("sram_sample", types)
            self.assertIn("capture_finished", types)
            self.assertTrue(
                "session_changed" in types or "sram_changed" in types
            )

            # Monotonic timestamps.
            mono = [item["t_mono_ns"] for item in timeline]
            self.assertEqual(mono, sorted(mono))

            metadata = json.loads(
                result.directory.joinpath("metadata.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["read_only"])
            self.assertEqual(metadata["sram_rf_pages"]["start"], 0xF0)

    def test_partial_capture_on_exception(self):
        class BoomClient(ScriptedClient):
            def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
                if tx[0] == 0x60:
                    raise RuntimeError("simulated failure")
                return super().iso14443_3_tdx(tx, max_rx_bytes, timeout_ms)

        clock = FakeClock()
        with tempfile.TemporaryDirectory() as tmp:
            config = LogicAnalyzerConfig(
                port="COM6",
                duration_s=1.0,
                interval_ms=50,
                output_dir=Path(tmp),
                wait_tag_s=1.0,
            )
            capture = LogicAnalyzerCapture(
                config,
                client_factory=lambda port, timeout: BoomClient(port, timeout),
                clock_ns=clock,
                wall_clock=lambda: "t",
                sleep=lambda s: None,
            )
            result = capture.run_safe()
            self.assertTrue(result.partial)
            self.assertTrue(result.directory.exists())
            text = result.directory.joinpath("timeline.jsonl").read_text(encoding="utf-8")
            self.assertIn("capture_finished", text)
            self.assertIn("rf_error", text)
            self.assertTrue(result.directory.joinpath("metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
