from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.analysis.trigger import (
    ACTIVE_NC,
    ACTIVE_NS,
    BASELINE_NC,
    BASELINE_NS,
    CONCLUSION_INCONCLUSIVE,
    CONCLUSION_OBSERVED,
    CONCLUSION_PROBABLE,
    CONCLUSION_REPEATABLE,
    SCENARIO_IDS,
    TriggerAnalysis,
    TriggerConfig,
)
from elatec_uid_tool.cli import build_parser
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


def baseline() -> bytes:
    return bytes((BASELINE_NC, 0x00, 0xF8, 0x48, 0x08, 0x01, BASELINE_NS, 0x00))


def active() -> bytes:
    return bytes((ACTIVE_NC, 0x00, 0xF8, 0x48, 0x08, 0x01, ACTIVE_NS, 0x00))


class ScriptedTriggerClient:
    """Scripted transport for trigger-analysis unit tests."""

    def __init__(self, port: str = "COM6", timeout: float = 2.0) -> None:
        self.port = port
        self.timeout = timeout
        self.mode = "stable_baseline"
        self.trigger_on = "get-version"  # which opcode/action arms transition
        self.latency_samples = 1
        self.return_after_samples = 3
        self._armed = False
        self._post_samples = 0
        self._session_calls = 0
        self.force_contaminated = False
        self.no_return = False
        self.sram_calls = 0
        self.search_count = 0
        self._get_version_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def search_tag(self, max_id_bytes: int = 32):
        self.search_count += 1
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self) -> None:
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        opcode = tx[0]
        if opcode == 0x60:  # GET_VERSION
            self._get_version_count += 1
            # Initial metadata GET_VERSION must not arm the scenario trigger.
            if self.trigger_on == "get-version" and self._get_version_count > 1:
                self._armed = True
                self._post_samples = 0
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x30:  # READ
            if self.trigger_on == "read-page-00":
                self._armed = True
                self._post_samples = 0
            return with_crc(bytes(16))
        if opcode == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0xF0:
                self.sram_calls += 1
                raise AssertionError("SRAM must not be used in trigger analysis")
            if start == 0x30 and end == 0x37:
                if self.trigger_on == "read-application-block":
                    self._armed = True
                    self._post_samples = 0
                return with_crc(bytes(32))
            if start == 0xEC and end == 0xED:
                self._session_calls += 1
                if self.trigger_on == "read-session":
                    # First session after arming path: treat this call as action.
                    # Action and monitor both use session reads; arm on first
                    # non-settle call after search bursts by counting.
                    pass
                return with_crc(self._next_session())
        raise AssertionError(f"Unexpected TX {tx.hex(' ').upper()}")

    def _next_session(self) -> bytes:
        if self.force_contaminated:
            return active()
        if not self._armed:
            return baseline()
        self._post_samples += 1
        if self._post_samples <= self.latency_samples:
            return baseline()
        if self.no_return:
            return active()
        if self._post_samples <= self.latency_samples + self.return_after_samples:
            return active()
        # Returned; stay baseline and disarm for next repetition settle.
        self._armed = False
        self._post_samples = 0
        return baseline()


class FakeClock:
    def __init__(self) -> None:
        self.ns = 0

    def __call__(self) -> int:
        return self.ns

    def advance(self, ns: int) -> None:
        self.ns += ns


def _run(tmp: str, client: ScriptedTriggerClient, **kwargs):
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.advance(int(seconds * 1_000_000_000))

    config = TriggerConfig(
        port="COM6",
        scenarios=kwargs.get("scenarios", ["get-version"]),
        duration_s=kwargs.get("duration_s", 0.2),
        interval_ms=kwargs.get("interval_ms", 40),
        settle_ms=kwargs.get("settle_ms", 80),
        repetitions=kwargs.get("repetitions", 3),
        output_dir=Path(tmp),
        verbose=False,
        wait_tag_s=1.0,
    )
    analysis = TriggerAnalysis(
        config,
        client_factory=lambda port, timeout: client,
        clock_ns=clock,
        wall_clock=lambda: "t",
        sleep=sleep,
    )
    return analysis.run()


class TriggerAnalysisTests(unittest.TestCase):
    def test_cli_parser(self):
        parser = build_parser()
        args = parser.parse_args(
            ["trigger-analysis", "--port", "COM6", "--all", "--verbose"]
        )
        self.assertTrue(args.all)
        self.assertEqual(args.duration, 2.0)
        self.assertEqual(args.settle_ms, 1500.0)
        args2 = parser.parse_args(
            ["trigger-analysis", "--scenario", "read-session"]
        )
        self.assertEqual(args2.scenario, "read-session")
        self.assertEqual(set(SCENARIO_IDS), set(SCENARIO_IDS))

    def test_stable_baseline_and_trigger_with_return(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "get-version"
        client.latency_samples = 1
        client.return_after_samples = 2
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=3)
            aggregate = result.metadata["aggregates"]["get-version"]
            self.assertGreaterEqual(aggregate["transition_repetitions"], 2)
            self.assertIn(
                aggregate["conclusion"],
                {
                    CONCLUSION_OBSERVED,
                    CONCLUSION_REPEATABLE,
                    CONCLUSION_PROBABLE,
                },
            )
            self.assertTrue((result.directory / "scenarios.csv").exists())
            self.assertTrue((result.directory / "report.txt").exists())
            timeline = [
                json.loads(line)
                for line in result.directory.joinpath("timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            mono = [item["t_mono_ns"] for item in timeline]
            self.assertEqual(mono, sorted(mono))
            self.assertEqual(client.sram_calls, 0)
            self.assertFalse(result.metadata["uses_sram"])

    def test_contaminated_scenario(self):
        client = ScriptedTriggerClient()
        client.force_contaminated = True
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=2, settle_ms=40)
            aggregate = result.metadata["aggregates"]["get-version"]
            self.assertEqual(aggregate["conclusion"], CONCLUSION_INCONCLUSIVE)
            self.assertGreaterEqual(aggregate["contaminated_repetitions"], 1)

    def test_missing_return_inconclusive(self):
        client = ScriptedTriggerClient()
        client.no_return = True
        client.latency_samples = 0
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=2, duration_s=0.12)
            details = result.metadata["aggregates"]["get-version"]["repetition_details"]
            self.assertTrue(any(item.get("active_observed") for item in details))
            self.assertTrue(
                any(not item.get("returned_to_baseline") for item in details if item.get("active_observed"))
            )

    def test_no_sram_in_all_scenarios_smoke(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "read-page-00"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["select-only", "read-page-00", "repeated-session-only"],
                repetitions=1,
                settle_ms=40,
                duration_s=0.08,
            )
            self.assertEqual(client.sram_calls, 0)
            self.assertEqual(result.metadata["forbidden_sram_ops"], 0)
            for scenario in result.metadata["aggregates"].values():
                self.assertFalse(scenario["uses_sram"])


if __name__ == "__main__":
    unittest.main()
