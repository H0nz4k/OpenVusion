from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.analysis.trigger import (
    ACTIVE_NC,
    ACTIVE_NS,
    BASELINE_CONFIRMED_AFTER_RETURN,
    BASELINE_NC,
    BASELINE_NS,
    BASELINE_OBSERVED,
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
    """Scripted transport modeling session-read-induced active window."""

    def __init__(self, port: str = "COM6", timeout: float = 2.0) -> None:
        self.port = port
        self.timeout = timeout
        self.trigger_on = "get-version"
        self.latency_samples = 1
        self.return_after_samples = 3
        self._armed = False
        self._post_samples = 0
        self._session_calls = 0
        self.force_active_pre_trigger = False
        self.no_return = False
        self.sram_calls = 0
        self.search_count = 0
        self._get_version_count = 0
        # Settle cycle: first session baseline, then active, then baseline.
        self.settle_cycle = True
        self._settle_phase = 0  # 0 baseline, 1 active..., 2 baseline done
        self._settle_active_left = 2

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def search_tag(self, max_id_bytes: int = 32):
        self.search_count += 1
        if self.trigger_on == "select-only" and self.search_count > 1:
            # Initial wait + later select-only trigger arms transition.
            self._armed = True
            self._post_samples = 0
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self) -> None:
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        opcode = tx[0]
        if opcode == 0x60:
            self._get_version_count += 1
            if self.trigger_on == "get-version" and self._get_version_count > 1:
                self._armed = True
                self._post_samples = 0
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x30:
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
                if self.trigger_on in ("read-session", "repeated-session-only"):
                    # Arm on first session after settle completed (phase >= 2)
                    # or when settle_cycle disabled and calls accumulate.
                    if self._settle_phase >= 2 or not self.settle_cycle:
                        if not self._armed:
                            self._armed = True
                            self._post_samples = 0
                return with_crc(self._next_session())
        raise AssertionError(f"Unexpected TX {tx.hex(' ').upper()}")

    def _next_session(self) -> bytes:
        if self.force_active_pre_trigger and self._settle_phase >= 2 and not self._armed:
            return active()

        if self.settle_cycle and self._settle_phase < 2 and not self._armed:
            if self._settle_phase == 0:
                self._settle_phase = 1
                self._settle_active_left = 2
                return baseline()
            if self._settle_phase == 1:
                self._settle_active_left -= 1
                if self._settle_active_left <= 0:
                    self._settle_phase = 2
                    return baseline()
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
        settle_ms=kwargs.get("settle_ms", 200),
        guard_ms=kwargs.get("guard_ms", 20),
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
        self.assertEqual(args.guard_ms, 200.0)
        args2 = parser.parse_args(
            ["trigger-analysis", "--scenario", "read-session"]
        )
        self.assertEqual(args2.scenario, "read-session")
        self.assertEqual(len(SCENARIO_IDS), 7)

    def test_settle_cycle_allows_scenario_with_single_baseline(self):
        client = ScriptedTriggerClient()
        client.settle_cycle = True
        client.trigger_on = "get-version"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, settle_ms=300)
            detail = result.metadata["aggregates"]["get-version"]["repetition_details"][0]
            self.assertTrue(detail["trigger_executed"])
            self.assertFalse(detail["contaminated"])
            self.assertIn(
                detail["baseline_method"],
                {BASELINE_OBSERVED, BASELINE_CONFIRMED_AFTER_RETURN},
            )
            self.assertIsNotNone(detail["rf_duration_us"])
            self.assertNotEqual(detail["rf_duration_us"], "")

    def test_active_pre_trigger_contaminates(self):
        client = ScriptedTriggerClient()
        client.settle_cycle = True
        client.force_active_pre_trigger = True
        client.trigger_on = "get-version"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, settle_ms=300)
            detail = result.metadata["aggregates"]["get-version"]["repetition_details"][0]
            self.assertTrue(detail["contaminated"])
            self.assertFalse(detail["trigger_executed"])
            self.assertEqual(detail["pre_trigger_state"], "active")
            self.assertEqual(
                result.metadata["aggregates"]["get-version"]["executed_repetitions"],
                0,
            )

    def test_select_only_uses_searchtag_as_trigger(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "select-only"
        client.settle_cycle = True
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["select-only"],
                repetitions=1,
                settle_ms=300,
            )
            detail = result.metadata["aggregates"]["select-only"]["repetition_details"][0]
            self.assertTrue(detail["trigger_executed"])
            self.assertEqual(detail["rf_operation"], "SearchTag")
            self.assertIsNotNone(detail["rf_duration_us"])
            # Preparatory reselect must not consume the scenario SearchTag:
            # wait_for_tag(1) + select-only trigger (>=1) => search_count >= 2
            self.assertGreaterEqual(client.search_count, 2)

    def test_repeated_session_only_first_read_is_trigger(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "repeated-session-only"
        client.settle_cycle = True
        client.latency_samples = 0
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["repeated-session-only"],
                repetitions=1,
                settle_ms=300,
                duration_s=0.2,
            )
            detail = result.metadata["aggregates"]["repeated-session-only"][
                "repetition_details"
            ][0]
            self.assertTrue(detail["trigger_executed"])
            self.assertEqual(detail["rf_operation"], "FAST_READ 3A EC ED")
            self.assertIsNotNone(detail["rf_duration_us"])
            self.assertTrue(detail["samples"])
            self.assertEqual(detail["samples"][0]["role"], "trigger_t0")

    def test_clean_scenarios_execute_and_fill_fields(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "get-version"
        client.latency_samples = 1
        client.return_after_samples = 2
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=3, settle_ms=300)
            aggregate = result.metadata["aggregates"]["get-version"]
            self.assertGreaterEqual(aggregate["executed_repetitions"], 2)
            self.assertGreaterEqual(aggregate["transition_repetitions"], 2)
            self.assertIn(
                aggregate["conclusion"],
                {
                    CONCLUSION_OBSERVED,
                    CONCLUSION_REPEATABLE,
                    CONCLUSION_PROBABLE,
                },
            )
            for detail in aggregate["repetition_details"]:
                if detail["trigger_executed"]:
                    self.assertIsNotNone(detail["rf_duration_us"])
                    self.assertTrue(detail["post_op_hex"])
                    self.assertTrue(detail["samples"])
                    self.assertTrue(detail["measurement_interference_possible"])
            self.assertEqual(client.sram_calls, 0)

    def test_single_baseline_not_auto_inconclusive(self):
        client = ScriptedTriggerClient()
        client.settle_cycle = False  # only single baselines, no multi-read confirm
        client.trigger_on = "get-version"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, settle_ms=80)
            detail = result.metadata["aggregates"]["get-version"]["repetition_details"][0]
            self.assertTrue(detail["trigger_executed"])
            # Must not be skipped merely due to single baseline sample.
            self.assertNotIn(
                "Baseline not stable",
                detail.get("note") or "",
            )

    def test_missing_return_inconclusive(self):
        client = ScriptedTriggerClient()
        client.no_return = True
        client.latency_samples = 0
        client.settle_cycle = True
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, duration_s=0.12, settle_ms=300)
            details = result.metadata["aggregates"]["get-version"]["repetition_details"]
            executed = [item for item in details if item.get("trigger_executed")]
            self.assertTrue(executed)
            self.assertTrue(any(item.get("active_observed") for item in executed))
            self.assertTrue(
                any(
                    not item.get("returned_to_baseline")
                    for item in executed
                    if item.get("active_observed")
                )
            )


if __name__ == "__main__":
    unittest.main()
