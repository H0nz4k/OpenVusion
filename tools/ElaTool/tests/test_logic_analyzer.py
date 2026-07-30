from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.capture.logic_analyzer import (
    FINISH_COMPLETED_ERRORS,
    FINISH_COMPLETED_SUCCESS,
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
        self.sram_mode = "ok"  # ok | nak | timeout
        self._sram_attempts = 0
        self.fail_first_session = False
        self._session_reads = 0

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
        from elatec_uid_tool.protocol import SerialCommunicationError

        opcode = tx[0]
        if opcode == 0x60:
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0xEC and end == 0xED:
                self._session_reads += 1
                if self.fail_first_session and self._session_reads == 1:
                    raise SerialCommunicationError(
                        "Tag neodpověděl na příkaz 3A EC ED."
                    )
                value = self._session_values[
                    min(self._session_index, len(self._session_values) - 1)
                ]
                self._session_index += 1
                return with_crc(value)
            if start == 0xF0 and end == 0xFF:
                self._sram_attempts += 1
                if self.sram_mode == "nak":
                    # First attempt NAK; further attempts would be a cascade bug.
                    if self._sram_attempts > 1:
                        raise SerialCommunicationError(
                            "Tag neodpověděl na příkaz 3A F0 FF."
                        )
                    return bytes([0x03])  # Type-2 NAK invalid address
                if self.sram_mode == "timeout":
                    raise SerialCommunicationError(
                        "Tag neodpověděl na příkaz 3A F0 FF."
                    )
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


def _run_capture(
    tmp: str,
    *,
    enable_sram: bool = False,
    session_only: bool = False,
    client: ScriptedClient | None = None,
    duration_s: float = 0.12,
    interval_ms: float = 40.0,
) -> tuple[LogicAnalyzerCapture, object, ScriptedClient]:
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.advance(int(seconds * 1_000_000_000))

    scripted = client or ScriptedClient()
    config = LogicAnalyzerConfig(
        port="COM6",
        duration_s=duration_s,
        interval_ms=interval_ms,
        output_dir=Path(tmp),
        enable_experimental_sram=enable_sram,
        session_only=session_only,
        verbose=False,
        wait_tag_s=1.0,
    )
    capture = LogicAnalyzerCapture(
        config,
        client_factory=lambda port, timeout: scripted,
        clock_ns=clock,
        wall_clock=lambda: "2026-07-31T00:00:00+02:00",
        sleep=sleep,
    )
    result = capture.run()
    return capture, result, scripted


class LogicAnalyzerTests(unittest.TestCase):
    def test_cli_parser_defaults_and_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            ["logic-analyzer", "--port", "COM6", "--session-only", "--verbose"]
        )
        self.assertEqual(args.command, "logic-analyzer")
        self.assertTrue(args.session_only)
        self.assertFalse(args.enable_experimental_sram)

        args2 = parser.parse_args(
            ["logic-analyzer", "--enable-experimental-sram", "--verbose"]
        )
        self.assertTrue(args2.enable_experimental_sram)

    def test_session_only_default_has_no_sram_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result, client = _run_capture(tmp, enable_sram=False)
            self.assertEqual(result.finish_status, FINISH_COMPLETED_SUCCESS)
            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            types = [item["event_type"] for item in timeline]
            self.assertIn("session_sample", types)
            self.assertNotIn("sram_sample", types)
            self.assertEqual(client._sram_attempts, 0)
            metadata = json.loads(
                result.directory.joinpath("metadata.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["session_only"])
            self.assertFalse(metadata["enable_experimental_sram"])
            report = result.directory.joinpath("report.txt").read_text(encoding="utf-8")
            self.assertIn("session: success=", report)
            self.assertIn("sram:    success=0", report)

    def test_experimental_sram_success_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result, _ = _run_capture(tmp, enable_sram=True)
            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            types = [item["event_type"] for item in timeline]
            self.assertIn("sram_sample", types)
            self.assertIn("session_changed", types)
            self.assertEqual(result.finish_status, FINISH_COMPLETED_SUCCESS)

    def test_first_sram_nak_disables_sampler_session_continues(self):
        client = ScriptedClient()
        client.sram_mode = "nak"

        with tempfile.TemporaryDirectory() as tmp:
            _, result, client = _run_capture(
                tmp,
                enable_sram=True,
                client=client,
                duration_s=0.16,
            )
            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            types = [item["event_type"] for item in timeline]
            self.assertIn("sampler_disabled", types)
            self.assertIn("tag_reselected", types)
            self.assertIn("session_sample", types)

            sram_errors = [
                item
                for item in timeline
                if item.get("event_type") == "rf_error"
                and item.get("rf_operation") == "FAST_READ 3A F0 FF"
            ]
            # Exactly one SRAM attempt/error — no timeout cascade.
            self.assertEqual(len(sram_errors), 1)
            self.assertEqual(client._sram_attempts, 1)

            session_ok = result.metadata["samplers"]["session"]["success"]
            self.assertGreaterEqual(session_ok, 2)
            self.assertEqual(result.metadata["samplers"]["sram"]["success"], 0)
            self.assertEqual(result.metadata["samplers"]["sram"]["failure"], 1)
            self.assertFalse(result.metadata["samplers"]["sram"]["enabled"])
            self.assertEqual(result.finish_status, FINISH_COMPLETED_ERRORS)

            report = result.directory.joinpath("report.txt").read_text(encoding="utf-8")
            self.assertIn("Finish status: completed_with_errors", report)
            self.assertIn("session: success=", report)

    def test_reselect_after_session_error(self):
        client = ScriptedClient()
        client.fail_first_session = True

        with tempfile.TemporaryDirectory() as tmp:
            _, result, client = _run_capture(
                tmp,
                enable_sram=False,
                client=client,
                duration_s=0.16,
            )
            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            types = [item["event_type"] for item in timeline]
            self.assertIn("tag_reselected", types)
            self.assertIn("tag_lost", types)
            self.assertGreaterEqual(client._search_count, 2)
            self.assertGreaterEqual(
                result.metadata["samplers"]["session"]["success"], 1
            )
            self.assertEqual(result.metadata["samplers"]["session"]["failure"], 1)
            self.assertEqual(result.finish_status, FINISH_COMPLETED_ERRORS)

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
            self.assertEqual(result.finish_status, "partial")
            text = result.directory.joinpath("timeline.jsonl").read_text(encoding="utf-8")
            self.assertIn("capture_finished", text)
            self.assertIn("rf_error", text)


if __name__ == "__main__":
    unittest.main()
