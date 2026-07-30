from __future__ import annotations

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
    CONCLUSION_GENERAL_RF,
    CONCLUSION_INCONCLUSIVE,
    CONCLUSION_OBSERVED,
    CONCLUSION_PROBABLE,
    CONCLUSION_REPEATABLE,
    CYCLE_CANONICAL,
    CYCLE_TRANSITIONAL,
    GLOBAL_RF_CONCLUSION,
    INTERMEDIATE_NC,
    INTERMEDIATE_NS,
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


def intermediate() -> bytes:
    return bytes(
        (INTERMEDIATE_NC, 0x00, 0xF8, 0x48, 0x08, 0x01, INTERMEDIATE_NS, 0x00)
    )


def active() -> bytes:
    return bytes((ACTIVE_NC, 0x00, 0xF8, 0x48, 0x08, 0x01, ACTIVE_NS, 0x00))


class ScriptedTriggerClient:
    """Scripted transport modeling session-read-induced wake window."""

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
        self.settle_cycle = True
        self._settle_phase = 0
        self._settle_active_left = 2
        # After arm: sequence of session payloads, then baseline forever.
        # None => default latency baseline then active then baseline.
        self.armed_sequence: list[bytes] | None = None
        self._seq_index = 0
        # Always-on sequence for every scenario after settle (for multi-scenario).
        self.universal_armed_sequence: list[bytes] | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def search_tag(self, max_id_bytes: int = 32):
        self.search_count += 1
        if self.trigger_on == "select-only" and self.search_count > 1:
            self._arm()
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self) -> None:
        return None

    def _arm(self) -> None:
        self._armed = True
        self._post_samples = 0
        self._seq_index = 0

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        opcode = tx[0]
        if opcode == 0x60:
            self._get_version_count += 1
            if self.trigger_on in ("get-version", "*") and self._get_version_count > 1:
                self._arm()
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x30:
            if self.trigger_on in ("read-page-00", "*"):
                self._arm()
            return with_crc(bytes(16))
        if opcode == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0xF0:
                self.sram_calls += 1
                raise AssertionError("SRAM must not be used in trigger analysis")
            if start == 0x30 and end == 0x37:
                if self.trigger_on in ("read-application-block", "*"):
                    self._arm()
                return with_crc(bytes(32))
            if start == 0xEC and end == 0xED:
                self._session_calls += 1
                if self.trigger_on in (
                    "read-session",
                    "repeated-session-only",
                    "*",
                ):
                    if self._settle_phase >= 2 or not self.settle_cycle:
                        if not self._armed:
                            self._arm()
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

        sequence = self.armed_sequence
        if sequence is None and self.universal_armed_sequence is not None:
            sequence = self.universal_armed_sequence
        if sequence is not None:
            if self._seq_index < len(sequence):
                payload = sequence[self._seq_index]
                self._seq_index += 1
                return payload
            self._armed = False
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


def _metrics_from_states(states: list[str], start_us: int = 1000, step_us: int = 50_000):
    analysis = TriggerAnalysis(TriggerConfig(port="COM6"))
    mapping = {
        "baseline": (BASELINE_NC, BASELINE_NS),
        "intermediate": (INTERMEDIATE_NC, INTERMEDIATE_NS),
        "active": (ACTIVE_NC, ACTIVE_NS),
        "other": (0x00, 0x00),
    }
    samples = []
    for index, state in enumerate(states):
        nc, ns = mapping[state]
        samples.append(
            {
                "elapsed_us": start_us + index * step_us,
                "raw_hex": "",
                "nc": nc,
                "ns": ns,
                "state": state,
                "role": "post_action" if index == 0 else "observation",
            }
        )
    result: dict = {}
    analysis._apply_cycle_metrics(result, samples)
    return result


class TriggerAnalysisTests(unittest.TestCase):
    def test_cli_parser(self):
        parser = build_parser()
        args = parser.parse_args(
            ["trigger-analysis", "--port", "COM6", "--all", "--verbose"]
        )
        self.assertTrue(args.all)
        self.assertEqual(args.guard_ms, 200.0)
        self.assertEqual(len(SCENARIO_IDS), 7)

    def test_cycle_baseline_intermediate_active_baseline(self):
        metrics = _metrics_from_states(
            ["intermediate", "active", "active", "baseline"]
        )
        self.assertEqual(metrics["cycle_kind"], CYCLE_CANONICAL)
        self.assertEqual(metrics["verdict"], CONCLUSION_OBSERVED)
        self.assertTrue(metrics["intermediate_observed"])
        self.assertTrue(metrics["canonical_active_observed"])
        self.assertTrue(metrics["returned_to_baseline"])
        self.assertEqual(metrics["first_nonbaseline_us"], 1000)
        self.assertEqual(metrics["first_transition_us"], 1000)
        self.assertEqual(metrics["intermediate_enter_us"], 1000)
        self.assertEqual(metrics["active_enter_us"], 51_000)
        self.assertEqual(metrics["return_us"], 151_000)
        self.assertEqual(metrics["intermediate_duration_us"], 50_000)
        self.assertEqual(metrics["canonical_active_duration_us"], 100_000)
        self.assertEqual(metrics["total_nonbaseline_window_us"], 150_000)
        self.assertEqual(metrics["active_window_us"], 150_000)

    def test_cycle_baseline_intermediate_baseline_transitional(self):
        metrics = _metrics_from_states(
            ["intermediate", "intermediate", "baseline"]
        )
        self.assertEqual(metrics["cycle_kind"], CYCLE_TRANSITIONAL)
        self.assertEqual(metrics["verdict"], CONCLUSION_OBSERVED)
        self.assertTrue(metrics["intermediate_observed"])
        self.assertFalse(metrics["canonical_active_observed"])
        self.assertIn("transitional", metrics["note"])

    def test_cycle_direct_baseline_active_baseline(self):
        metrics = _metrics_from_states(["active", "active", "baseline"])
        self.assertEqual(metrics["cycle_kind"], CYCLE_CANONICAL)
        self.assertEqual(metrics["verdict"], CONCLUSION_OBSERVED)
        self.assertFalse(metrics["intermediate_observed"])
        self.assertTrue(metrics["canonical_active_observed"])
        self.assertEqual(metrics["first_nonbaseline_us"], 1000)
        self.assertEqual(metrics["active_enter_us"], 1000)
        self.assertEqual(metrics["total_nonbaseline_window_us"], 100_000)

    def test_post_action_intermediate_fills_first_transition(self):
        metrics = _metrics_from_states(
            ["intermediate", "active", "baseline"], start_us=777
        )
        self.assertEqual(metrics["first_transition_us"], 777)
        self.assertEqual(metrics["intermediate_enter_us"], 777)

    def test_read_page_00_not_false_inconclusive(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "read-page-00"
        client.settle_cycle = True
        client.armed_sequence = [
            intermediate(),
            active(),
            active(),
            baseline(),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["read-page-00"],
                repetitions=1,
                settle_ms=300,
                duration_s=0.25,
            )
            detail = result.metadata["aggregates"]["read-page-00"][
                "repetition_details"
            ][0]
            self.assertTrue(detail["trigger_executed"])
            self.assertEqual(detail["verdict"], CONCLUSION_OBSERVED)
            self.assertNotEqual(detail["verdict"], CONCLUSION_INCONCLUSIVE)
            self.assertTrue(detail["intermediate_observed"])
            self.assertTrue(detail["canonical_active_observed"])
            self.assertTrue(detail["returned_to_baseline"])
            self.assertIsNotNone(detail["first_nonbaseline_us"])
            self.assertIsNotNone(detail["active_enter_us"])
            self.assertIsNotNone(detail["total_nonbaseline_window_us"])
            self.assertEqual(
                detail["active_window_us"], detail["total_nonbaseline_window_us"]
            )

    def test_aggregation_intermediate_and_canonical(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "read-page-00"
        client.armed_sequence = [
            intermediate(),
            active(),
            baseline(),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["read-page-00"],
                repetitions=3,
                settle_ms=300,
                duration_s=0.25,
            )
            aggregate = result.metadata["aggregates"]["read-page-00"]
            self.assertEqual(aggregate["transition_repetitions"], 3)
            self.assertEqual(aggregate["canonical_active_repetitions"], 3)
            self.assertEqual(aggregate["intermediate_repetitions"], 3)
            self.assertGreater(aggregate["state_counts"]["intermediate"], 0)
            self.assertGreater(aggregate["state_counts"]["active"], 0)
            self.assertNotEqual(aggregate["conclusion"], CONCLUSION_PROBABLE)

    def test_global_general_rf_association(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "*"
        client.settle_cycle = True
        client.universal_armed_sequence = [
            intermediate(),
            active(),
            baseline(),
        ]

        def search_tag(max_id_bytes: int = 32):
            client.search_count += 1
            # wait_for_tag (1) + select-only trigger (2); do not arm prep reselects.
            if client.search_count == 2:
                client._arm()
            return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

        client.search_tag = search_tag  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=[
                    "select-only",
                    "get-version",
                    "read-page-00",
                    "read-session",
                ],
                repetitions=1,
                settle_ms=300,
                duration_s=0.25,
            )
            self.assertEqual(
                result.metadata.get("global_conclusion"), GLOBAL_RF_CONCLUSION
            )
            for name in (
                "select-only",
                "get-version",
                "read-page-00",
                "read-session",
            ):
                self.assertEqual(
                    result.metadata["aggregates"][name]["conclusion"],
                    CONCLUSION_GENERAL_RF,
                )
            # probable trigger must not be used loosely
            conclusions = [
                agg["conclusion"] for agg in result.metadata["aggregates"].values()
            ]
            self.assertNotIn(CONCLUSION_PROBABLE, conclusions)

    def test_probable_trigger_not_assigned_for_local_repeatability(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "get-version"
        client.latency_samples = 0
        client.return_after_samples = 2
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["get-version"],
                repetitions=3,
                settle_ms=300,
            )
            conclusion = result.metadata["aggregates"]["get-version"]["conclusion"]
            self.assertIn(
                conclusion,
                {CONCLUSION_OBSERVED, CONCLUSION_REPEATABLE},
            )
            self.assertNotEqual(conclusion, CONCLUSION_PROBABLE)
            self.assertIsNone(result.metadata.get("global_conclusion"))

    def test_settle_cycle_allows_scenario_with_single_baseline(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "get-version"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, settle_ms=300)
            detail = result.metadata["aggregates"]["get-version"]["repetition_details"][0]
            self.assertTrue(detail["trigger_executed"])
            self.assertIn(
                detail["baseline_method"],
                {BASELINE_OBSERVED, BASELINE_CONFIRMED_AFTER_RETURN},
            )

    def test_active_pre_trigger_contaminates(self):
        client = ScriptedTriggerClient()
        client.force_active_pre_trigger = True
        client.trigger_on = "get-version"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, settle_ms=300)
            detail = result.metadata["aggregates"]["get-version"]["repetition_details"][0]
            self.assertTrue(detail["contaminated"])
            self.assertFalse(detail["trigger_executed"])

    def test_select_only_uses_searchtag_as_trigger(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "select-only"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["select-only"],
                repetitions=1,
                settle_ms=300,
            )
            detail = result.metadata["aggregates"]["select-only"]["repetition_details"][0]
            self.assertEqual(detail["rf_operation"], "SearchTag")
            self.assertTrue(detail["trigger_executed"])

    def test_repeated_session_only_first_read_is_trigger(self):
        client = ScriptedTriggerClient()
        client.trigger_on = "repeated-session-only"
        client.latency_samples = 0
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                tmp,
                client,
                scenarios=["repeated-session-only"],
                repetitions=1,
                settle_ms=300,
            )
            detail = result.metadata["aggregates"]["repeated-session-only"][
                "repetition_details"
            ][0]
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
            for detail in aggregate["repetition_details"]:
                if detail["trigger_executed"]:
                    self.assertIsNotNone(detail["rf_duration_us"])
                    self.assertTrue(detail["measurement_interference_possible"])
            self.assertEqual(client.sram_calls, 0)

    def test_missing_return_inconclusive(self):
        client = ScriptedTriggerClient()
        client.no_return = True
        client.latency_samples = 0
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, client, repetitions=1, duration_s=0.12, settle_ms=300)
            details = result.metadata["aggregates"]["get-version"]["repetition_details"]
            executed = [item for item in details if item.get("trigger_executed")]
            self.assertTrue(executed)
            self.assertTrue(
                any(item.get("canonical_active_observed") for item in executed)
            )
            self.assertTrue(
                any(not item.get("returned_to_baseline") for item in executed)
            )


if __name__ == "__main__":
    unittest.main()
