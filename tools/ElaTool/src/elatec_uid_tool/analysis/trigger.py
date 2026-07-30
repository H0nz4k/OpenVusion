from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

from ..capture.writer import capture_dir_name, create_capture_dir
from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient


BASELINE_NC = 0x19
BASELINE_NS = 0x01
INTERMEDIATE_NC = 0x7C
INTERMEDIATE_NS = 0x41
ACTIVE_NC = 0x7C
ACTIVE_NS = 0x29

STATE_BASELINE = "baseline"
STATE_INTERMEDIATE = "intermediate"
STATE_ACTIVE = "active"
STATE_OTHER = "other"

SCENARIO_IDS = (
    "select-only",
    "get-version",
    "read-page-00",
    "read-application-block",
    "read-session",
    "get-version-then-session",
    "repeated-session-only",
)

SCENARIOS_WITH_PREP_RESELECT = (
    "get-version",
    "read-page-00",
    "read-application-block",
    "read-session",
    "get-version-then-session",
    "repeated-session-only",
)

SCENARIOS_SKIP_PRE_TRIGGER_PROBE = (
    "select-only",
    "read-session",
    "repeated-session-only",
)

CONCLUSION_OBSERVED = "observed association"
CONCLUSION_REPEATABLE = "repeatable association"
CONCLUSION_GENERAL_RF = "general RF association"
CONCLUSION_PROBABLE = "probable trigger"  # retained for import compat; not assigned
CONCLUSION_INCONCLUSIVE = "inconclusive"

CYCLE_CANONICAL = "canonical_active_cycle"
CYCLE_TRANSITIONAL = "transitional_cycle"
CYCLE_INCOMPLETE = "incomplete"
CYCLE_NONE = "none"

BASELINE_OBSERVED = "baseline_observed"
BASELINE_CONFIRMED_AFTER_RETURN = "baseline_confirmed_after_return"
BASELINE_STABLE_MULTI = "baseline_stable_by_multiple_reads"

GLOBAL_RF_CONCLUSION = (
    "Results are consistent with a general RF/select-associated host wake-up, "
    "not a command-specific trigger."
)


@dataclass
class TriggerConfig:
    port: str
    scenarios: list[str] = field(default_factory=lambda: list(SCENARIO_IDS))
    duration_s: float = 2.0
    interval_ms: float = 50.0
    settle_ms: float = 1500.0
    guard_ms: float = 200.0
    repetitions: int = 3
    output_dir: Path = field(
        default_factory=lambda: Path("captures") / "trigger-analysis"
    )
    verbose: bool = False
    timeout: float = 2.0
    wait_tag_s: float = 15.0


@dataclass
class TriggerResult:
    directory: Path
    uid: str | None
    metadata: dict[str, Any]


@dataclass
class SettleOutcome:
    ready: bool
    method: str | None
    sample_count: int
    completed_active_cycle: bool
    unfinished_active_cycle: bool
    last_state: str | None
    last_sample: bytes | None
    error: str | None = None


class TriggerAnalysis:
    """Read-only RF trigger association study (no SRAM)."""

    def __init__(
        self,
        config: TriggerConfig,
        *,
        client_factory: Callable[[str, float], Any] | None = None,
        clock_ns: Callable[[], int] | None = None,
        wall_clock: Callable[[], str] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or (
            lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)
        )
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._wall_clock = wall_clock or (
            lambda: datetime.now().astimezone().isoformat()
        )
        self._sleep = sleep or time.sleep
        self._seq = 0
        self._t0_ns = 0
        self._uid: str | None = None
        self._timeline: list[dict[str, Any]] = []
        self._errors: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] = []
        self._forbidden_sram_ops = 0

    def run(self) -> TriggerResult:
        config = self.config
        unknown = [name for name in config.scenarios if name not in SCENARIO_IDS]
        if unknown:
            raise ValueError(f"Neznámé scénáře: {', '.join(unknown)}")

        directory = create_capture_dir(
            Path(config.output_dir),
            "pending",
            when=datetime.now(),
        )
        self._t0_ns = self._clock_ns()
        metadata: dict[str, Any] = {
            "schema": 3,
            "tool": "trigger-analysis",
            "read_only": True,
            "uses_sram": False,
            "started_at": self._wall_clock(),
            "port": config.port,
            "duration_s": config.duration_s,
            "interval_ms": config.interval_ms,
            "settle_ms": config.settle_ms,
            "guard_ms": config.guard_ms,
            "repetitions": config.repetitions,
            "scenarios": list(config.scenarios),
            "states": {
                "baseline": {"NC_REG": BASELINE_NC, "NS_REG": BASELINE_NS},
                "intermediate": {
                    "NC_REG": INTERMEDIATE_NC,
                    "NS_REG": INTERMEDIATE_NS,
                },
                "active": {"NC_REG": ACTIVE_NC, "NS_REG": ACTIVE_NS},
            },
            "baseline": {"NC_REG": BASELINE_NC, "NS_REG": BASELINE_NS},
            "active": {"NC_REG": ACTIVE_NC, "NS_REG": ACTIVE_NS},
            "intermediate": {
                "NC_REG": INTERMEDIATE_NC,
                "NS_REG": INTERMEDIATE_NS,
            },
            "baseline_policy": (
                "first-sample baseline is valid; multiple consecutive baseline "
                "reads are optional because session reads themselves may trigger "
                "the non-baseline window"
            ),
            "active_window_us_meaning": (
                "active_window_us equals total_nonbaseline_window_us "
                "(first non-baseline sample → return to baseline), not only "
                "canonical 0x7C/0x29 dwell time"
            ),
            "searchtag_duration_note": (
                "SearchTag rf_duration_us is transport/API wall time "
                "(may be hundreds of ms), not pure RF-frame duration"
            ),
            "isolation_note": (
                "Best-effort settle/reselect only. Not an isolated RF field; "
                "do not treat results as confirmed causality. "
                "Session reads used for settle/probe may themselves interfere."
            ),
        }

        client = self._client_factory(config.port, config.timeout)
        entered = False
        aggregates: dict[str, Any] = {}

        try:
            enter = getattr(client, "__enter__", None)
            if callable(enter):
                client = enter()
                entered = True

            tag = self._wait_for_tag(client)
            self._uid = tag.id_hex
            self._emit(
                "tag_detected",
                decoded={"uid": self._uid, "tag_type": tag.tag_type},
                rf_operation="SearchTag",
            )
            ntag = NtagI2CPlus(client)
            version = ntag.get_version()
            self._emit(
                "get_version",
                rf_operation="GET_VERSION 60",
                raw_hex=version.raw.hex(" ").upper(),
            )
            metadata["uid"] = self._uid
            metadata["get_version"] = version.raw.hex(" ").upper()

            for scenario in config.scenarios:
                aggregates[scenario] = self._run_scenario(ntag, scenario)

            self._apply_global_conclusions(aggregates, metadata)
        finally:
            metadata["finished_at"] = self._wall_clock()
            metadata["aggregates"] = aggregates
            metadata["forbidden_sram_ops"] = self._forbidden_sram_ops
            metadata["uid"] = self._uid
            self._write_outputs(directory, metadata, aggregates)
            try:
                client.set_rf_off()
            except Exception:
                pass
            if entered:
                exit_ = getattr(client, "__exit__", None)
                if callable(exit_):
                    try:
                        exit_(None, None, None)
                    except Exception:
                        pass
            directory = self._rename(directory)

        return TriggerResult(directory=directory, uid=self._uid, metadata=metadata)

    def _run_scenario(self, ntag: NtagI2CPlus, scenario: str) -> dict[str, Any]:
        reps: list[dict[str, Any]] = []
        for repetition in range(1, self.config.repetitions + 1):
            reps.append(self._run_repetition(ntag, scenario, repetition))
        aggregate = self._aggregate(scenario, reps)
        if self.config.verbose:
            print(
                f"[aggregate] {scenario}: {aggregate['conclusion']} "
                f"(executed={aggregate['executed_repetitions']}/"
                f"{aggregate['repetitions']}, "
                f"transitions={aggregate['transition_repetitions']}, "
                f"canonical={aggregate['canonical_active_repetitions']}, "
                f"intermediate={aggregate['intermediate_repetitions']})"
            )
        return aggregate

    def _run_repetition(
        self,
        ntag: NtagI2CPlus,
        scenario: str,
        repetition: int,
    ) -> dict[str, Any]:
        config = self.config
        self._emit(
            "scenario_started",
            decoded={"scenario": scenario, "repetition": repetition},
        )

        result: dict[str, Any] = {
            "scenario": scenario,
            "repetition": repetition,
            "settled": False,
            "reselected": False,
            "baseline_hex": None,
            "baseline_method": None,
            "baseline_sample_count": 0,
            "baseline_stable_by_multiple_reads": False,
            "pre_trigger_state": None,
            "measurement_interference_possible": False,
            "trigger_executed": False,
            "contaminated": False,
            "rf_operation": None,
            "rf_duration_us": None,
            "post_op_hex": None,
            "first_nonbaseline_us": None,
            "first_transition_us": None,
            "intermediate_enter_us": None,
            "active_enter_us": None,
            "return_us": None,
            "intermediate_duration_us": None,
            "canonical_active_duration_us": None,
            "total_nonbaseline_window_us": None,
            "active_window_us": None,
            "transition_count": 0,
            "intermediate_observed": False,
            "canonical_active_observed": False,
            "active_observed": False,
            "returned_to_baseline": False,
            "cycle_kind": CYCLE_NONE,
            "errors": [],
            "verdict": CONCLUSION_INCONCLUSIVE,
            "samples": [],
            "note": None,
        }

        settle = self._settle_to_baseline(ntag)
        result["settled"] = settle.ready
        result["baseline_sample_count"] = settle.sample_count
        result["baseline_method"] = settle.method
        if settle.last_sample is not None:
            result["baseline_hex"] = settle.last_sample.hex(" ").upper()

        if settle.error:
            result["errors"].append(settle.error)
            result["contaminated"] = True
            result["note"] = f"RF error during settle: {settle.error}"
            result["trigger_executed"] = False
            return self._finish_repetition(result, scenario, repetition)

        if settle.unfinished_active_cycle:
            result["contaminated"] = True
            result["pre_trigger_state"] = settle.last_state or "active"
            result["note"] = "Unfinished non-baseline cycle at end of settle."
            result["trigger_executed"] = False
            return self._finish_repetition(result, scenario, repetition)

        if not settle.ready or settle.last_sample is None or not self._is_baseline(
            settle.last_sample
        ):
            result["contaminated"] = True
            result["pre_trigger_state"] = settle.last_state or "unknown"
            result["note"] = "Baseline not available after settle."
            result["trigger_executed"] = False
            return self._finish_repetition(result, scenario, repetition)

        baseline_snapshot = settle.last_sample
        result["baseline_hex"] = baseline_snapshot.hex(" ").upper()

        if scenario in SCENARIOS_WITH_PREP_RESELECT:
            result["reselected"] = self._reselect(ntag.client)
            if not result["reselected"]:
                result["contaminated"] = True
                result["note"] = "Preparatory SearchTag/reselect failed."
                result["trigger_executed"] = False
                return self._finish_repetition(result, scenario, repetition)

        if scenario not in SCENARIOS_SKIP_PRE_TRIGGER_PROBE:
            try:
                probe, probe_us = self._timed(ntag.read_session_registers)
            except (ElatecError, SerialCommunicationError) as exc:
                result["errors"].append(str(exc))
                result["contaminated"] = True
                result["note"] = f"RF error before trigger: {exc}"
                result["trigger_executed"] = False
                self._emit("rf_error", error=str(exc), rf_operation="FAST_READ 3A EC ED")
                self._recover(ntag.client)
                return self._finish_repetition(result, scenario, repetition)

            result["measurement_interference_possible"] = True
            result["pre_trigger_state"] = self._classify(probe)
            result["baseline_sample_count"] += 1
            self._emit(
                "baseline_sample",
                rf_operation="FAST_READ 3A EC ED",
                rf_duration_us=probe_us,
                raw_hex=probe.hex(" ").upper(),
                decoded={
                    "phase": "pre_trigger_probe",
                    "state": result["pre_trigger_state"],
                    "measurement_interference_possible": True,
                    "baseline_method": result["baseline_method"],
                },
            )
            if self._is_active(probe):
                result["contaminated"] = True
                result["note"] = "Pre-trigger state is active (0x7C/0x29)."
                result["trigger_executed"] = False
                return self._finish_repetition(result, scenario, repetition)
            if self._is_intermediate(probe):
                result["contaminated"] = True
                result["note"] = "Pre-trigger state is intermediate (0x7C/0x41)."
                result["trigger_executed"] = False
                return self._finish_repetition(result, scenario, repetition)
            if not self._is_baseline(probe):
                result["contaminated"] = True
                result["note"] = f"Pre-trigger state unknown: {result['pre_trigger_state']}."
                result["trigger_executed"] = False
                return self._finish_repetition(result, scenario, repetition)
            baseline_snapshot = probe
            result["baseline_hex"] = probe.hex(" ").upper()
        else:
            result["pre_trigger_state"] = "baseline"
            result["measurement_interference_possible"] = True

        trigger_t0_elapsed: int | None = None
        try:
            if scenario == "repeated-session-only":
                op_data, op_us = self._timed(ntag.read_session_registers)
                rf_name = "FAST_READ 3A EC ED"
                trigger_t0_elapsed = self._elapsed_us()
                result["rf_operation"] = rf_name
                result["rf_duration_us"] = op_us
                result["post_op_hex"] = op_data.hex(" ").upper()
                result["trigger_executed"] = True
                self._emit(
                    "scenario_action",
                    rf_operation=rf_name,
                    rf_duration_us=op_us,
                    raw_hex=result["post_op_hex"],
                    decoded={
                        "scenario": scenario,
                        "repetition": repetition,
                        "role": "first_session_read_is_trigger_t0",
                    },
                )
                post = op_data
            elif scenario == "select-only":
                started = self._clock_ns()
                tag = ntag.client.search_tag()
                finished = self._clock_ns()
                op_us = (finished - started) // 1000
                if tag is None:
                    raise SerialCommunicationError(
                        "select-only: SearchTag nenašel tag."
                    )
                trigger_t0_elapsed = self._elapsed_us()
                result["rf_operation"] = "SearchTag"
                result["rf_duration_us"] = op_us
                result["trigger_executed"] = True
                self._emit(
                    "scenario_action",
                    rf_operation="SearchTag",
                    rf_duration_us=op_us,
                    raw_hex=tag.id_bytes.hex(" ").upper(),
                    decoded={
                        "scenario": scenario,
                        "repetition": repetition,
                        "uid": tag.id_hex,
                        "duration_kind": "transport_api",
                    },
                )
                post, post_us = self._timed(ntag.read_session_registers)
                result["post_op_hex"] = post.hex(" ").upper()
                self._emit(
                    "session_sample",
                    rf_operation="FAST_READ 3A EC ED",
                    rf_duration_us=post_us,
                    raw_hex=result["post_op_hex"],
                    decoded={
                        "phase": "post_action",
                        "scenario": scenario,
                        "state": self._classify(post),
                    },
                )
            else:
                op_data, op_us, rf_name = self._execute_scenario_action(ntag, scenario)
                trigger_t0_elapsed = self._elapsed_us()
                result["rf_operation"] = rf_name
                result["rf_duration_us"] = op_us
                result["trigger_executed"] = True
                raw_hex = (
                    op_data.hex(" ").upper()
                    if isinstance(op_data, (bytes, bytearray))
                    else None
                )
                self._emit(
                    "scenario_action",
                    rf_operation=rf_name,
                    rf_duration_us=op_us,
                    raw_hex=raw_hex,
                    decoded={"scenario": scenario, "repetition": repetition},
                )
                if scenario == "read-session":
                    post = op_data
                    result["post_op_hex"] = post.hex(" ").upper()
                else:
                    post, post_us = self._timed(ntag.read_session_registers)
                    result["post_op_hex"] = post.hex(" ").upper()
                    self._emit(
                        "session_sample",
                        rf_operation="FAST_READ 3A EC ED",
                        rf_duration_us=post_us,
                        raw_hex=result["post_op_hex"],
                        decoded={
                            "phase": "post_action",
                            "scenario": scenario,
                            "state": self._classify(post),
                        },
                    )
        except (ElatecError, SerialCommunicationError, ValueError, RuntimeError) as exc:
            result["errors"].append(str(exc))
            result["contaminated"] = True
            result["note"] = f"RF error during/before trigger: {exc}"
            result["trigger_executed"] = False
            self._emit("rf_error", error=str(exc), rf_operation=scenario)
            self._recover(ntag.client)
            return self._finish_repetition(result, scenario, repetition)

        samples = [
            {
                "elapsed_us": (
                    trigger_t0_elapsed
                    if trigger_t0_elapsed is not None
                    else self._elapsed_us()
                ),
                "raw_hex": result["post_op_hex"],
                "nc": post[0],
                "ns": post[6],
                "state": self._classify(post),
                "role": (
                    "trigger_t0"
                    if scenario in ("repeated-session-only", "read-session")
                    else "post_action"
                ),
            }
        ]

        previous = post
        transitions = 0
        if not self._is_baseline(post):
            transitions = 1

        deadline = self._clock_ns() + int(config.duration_s * 1_000_000_000)
        next_sample = self._clock_ns()
        interval_ns = int(config.interval_ms * 1_000_000)

        while self._clock_ns() < deadline:
            now = self._clock_ns()
            if now < next_sample:
                self._sleep((next_sample - now) / 1_000_000_000)
            try:
                current, rf_us = self._timed(ntag.read_session_registers)
            except (ElatecError, SerialCommunicationError) as exc:
                result["errors"].append(str(exc))
                self._emit(
                    "rf_error",
                    error=str(exc),
                    rf_operation="FAST_READ 3A EC ED",
                )
                self._recover(ntag.client)
                next_sample = self._clock_ns() + interval_ns
                continue

            elapsed = self._elapsed_us()
            state = self._classify(current)
            samples.append(
                {
                    "elapsed_us": elapsed,
                    "raw_hex": current.hex(" ").upper(),
                    "nc": current[0],
                    "ns": current[6],
                    "state": state,
                    "role": "observation",
                }
            )
            self._emit(
                "session_sample",
                rf_operation="FAST_READ 3A EC ED",
                rf_duration_us=rf_us,
                raw_hex=current.hex(" ").upper(),
                decoded={
                    "phase": "monitor",
                    "scenario": scenario,
                    "state": state,
                },
            )

            if previous != current:
                transitions += 1
            previous = current
            next_sample += interval_ns
            if next_sample < self._clock_ns():
                next_sample = self._clock_ns() + interval_ns

        result["samples"] = samples
        result["transition_count"] = transitions
        self._apply_cycle_metrics(result, samples)

        if self.config.verbose:
            print(
                f"[{scenario} #{repetition}] "
                f"executed={result['trigger_executed']} "
                f"cycle={result['cycle_kind']} "
                f"inter={result['intermediate_observed']} "
                f"active={result['canonical_active_observed']} "
                f"return={result['returned_to_baseline']} "
                f"verdict={result['verdict']}"
            )

        return self._finish_repetition(result, scenario, repetition)

    def _apply_cycle_metrics(
        self,
        result: dict[str, Any],
        samples: list[dict[str, Any]],
    ) -> None:
        first_nonbaseline_us: int | None = None
        intermediate_enter_us: int | None = None
        active_enter_us: int | None = None
        return_us: int | None = None
        intermediate_observed = False
        canonical_active_observed = False
        returned_to_baseline = False
        left_baseline = False

        for sample in samples:
            state = sample["state"]
            elapsed = sample["elapsed_us"]
            if state != STATE_BASELINE:
                if first_nonbaseline_us is None:
                    first_nonbaseline_us = elapsed
                    left_baseline = True
                if state == STATE_INTERMEDIATE:
                    intermediate_observed = True
                    if intermediate_enter_us is None:
                        intermediate_enter_us = elapsed
                elif state == STATE_ACTIVE:
                    canonical_active_observed = True
                    if active_enter_us is None:
                        active_enter_us = elapsed
            elif left_baseline and return_us is None:
                return_us = elapsed
                returned_to_baseline = True

        intermediate_duration_us = None
        if intermediate_enter_us is not None:
            if active_enter_us is not None:
                intermediate_duration_us = active_enter_us - intermediate_enter_us
            elif return_us is not None:
                intermediate_duration_us = return_us - intermediate_enter_us

        canonical_active_duration_us = None
        if active_enter_us is not None and return_us is not None:
            canonical_active_duration_us = return_us - active_enter_us

        total_nonbaseline_window_us = None
        if first_nonbaseline_us is not None and return_us is not None:
            total_nonbaseline_window_us = return_us - first_nonbaseline_us

        if (
            returned_to_baseline
            and intermediate_observed
            and canonical_active_observed
        ):
            cycle_kind = CYCLE_CANONICAL
            verdict = CONCLUSION_OBSERVED
            note = "baseline -> intermediate -> active -> baseline"
        elif returned_to_baseline and canonical_active_observed:
            cycle_kind = CYCLE_CANONICAL
            verdict = CONCLUSION_OBSERVED
            note = "baseline -> active -> baseline"
        elif returned_to_baseline and intermediate_observed:
            cycle_kind = CYCLE_TRANSITIONAL
            verdict = CONCLUSION_OBSERVED
            note = "observed transitional cycle (intermediate without canonical active)"
        elif left_baseline and not returned_to_baseline:
            cycle_kind = CYCLE_INCOMPLETE
            verdict = CONCLUSION_INCONCLUSIVE
            note = "Non-baseline state observed but no return within duration."
        else:
            cycle_kind = CYCLE_NONE
            verdict = CONCLUSION_INCONCLUSIVE
            note = "No baseline->non-baseline transition observed."

        result["first_nonbaseline_us"] = first_nonbaseline_us
        result["first_transition_us"] = first_nonbaseline_us
        result["intermediate_enter_us"] = intermediate_enter_us
        result["active_enter_us"] = active_enter_us
        result["return_us"] = return_us
        result["intermediate_duration_us"] = intermediate_duration_us
        result["canonical_active_duration_us"] = canonical_active_duration_us
        result["total_nonbaseline_window_us"] = total_nonbaseline_window_us
        # Compat: active_window_us == total non-baseline window.
        result["active_window_us"] = total_nonbaseline_window_us
        result["intermediate_observed"] = intermediate_observed
        result["canonical_active_observed"] = canonical_active_observed
        result["active_observed"] = canonical_active_observed
        result["returned_to_baseline"] = returned_to_baseline
        result["cycle_kind"] = cycle_kind
        result["verdict"] = verdict
        result["note"] = note

    def _finish_repetition(
        self,
        result: dict[str, Any],
        scenario: str,
        repetition: int,
    ) -> dict[str, Any]:
        if not result.get("trigger_executed"):
            result["verdict"] = CONCLUSION_INCONCLUSIVE
            if not result.get("note"):
                result["note"] = "Trigger was not executed."
        self._rows.append(self._row_from_result(result))
        self._emit(
            "scenario_finished",
            decoded={
                "scenario": scenario,
                "repetition": repetition,
                "verdict": result["verdict"],
                "trigger_executed": result.get("trigger_executed"),
                "contaminated": result.get("contaminated"),
                "baseline_method": result.get("baseline_method"),
                "cycle_kind": result.get("cycle_kind"),
                "note": result.get("note"),
            },
        )
        return result

    def _execute_scenario_action(
        self,
        ntag: NtagI2CPlus,
        scenario: str,
    ) -> tuple[Any, int, str]:
        if scenario == "read-sram":
            self._forbidden_sram_ops += 1
            raise RuntimeError("SRAM is forbidden in trigger analysis.")

        if scenario == "get-version":
            data, us = self._timed(ntag.get_version)
            return data, us, "GET_VERSION 60"

        if scenario == "read-page-00":
            data, us = self._timed(lambda: ntag.read_block(0x00))
            return data, us, "READ 30 00"

        if scenario == "read-application-block":
            data, us = self._timed(
                lambda: ntag.read_eeprom_range(
                    EEPROM_WATCH_START_PAGE,
                    EEPROM_WATCH_END_PAGE,
                )
            )
            return data, us, "FAST_READ 3A 30 37"

        if scenario == "read-session":
            data, us = self._timed(ntag.read_session_registers)
            return data, us, "FAST_READ 3A EC ED"

        if scenario == "get-version-then-session":
            started = self._clock_ns()
            version = ntag.get_version()
            session = ntag.read_session_registers()
            finished = self._clock_ns()
            return (
                version.raw + session,
                (finished - started) // 1000,
                "GET_VERSION+FAST_READ_SESSION",
            )

        raise ValueError(f"Neznámý scénář pro action helper: {scenario}")

    def _settle_to_baseline(self, ntag: NtagI2CPlus) -> SettleOutcome:
        """Settle without requiring consecutive baseline reads."""
        deadline = self._clock_ns() + int(self.config.settle_ms * 1_000_000)
        samples: list[bytes] = []
        seen_baseline = False
        seen_nonbaseline_after_baseline = False
        completed_cycle = False
        first_baseline: bytes | None = None
        consecutive_baseline = 0
        max_consecutive_baseline = 0
        last: bytes | None = None
        error: str | None = None

        while self._clock_ns() < deadline:
            try:
                data, rf_us = self._timed(ntag.read_session_registers)
            except (ElatecError, SerialCommunicationError) as exc:
                error = str(exc)
                self._emit(
                    "rf_error",
                    error=error,
                    rf_operation="FAST_READ 3A EC ED",
                )
                self._recover(ntag.client)
                self._sleep(self.config.interval_ms / 1000.0)
                continue

            samples.append(data)
            last = data
            state = self._classify(data)
            self._emit(
                "session_sample",
                rf_operation="FAST_READ 3A EC ED",
                rf_duration_us=rf_us,
                raw_hex=data.hex(" ").upper(),
                decoded={"phase": "settle", "state": state},
            )

            if self._is_baseline(data):
                consecutive_baseline += 1
                max_consecutive_baseline = max(
                    max_consecutive_baseline, consecutive_baseline
                )
                if not seen_baseline:
                    seen_baseline = True
                    first_baseline = data
                if seen_nonbaseline_after_baseline:
                    completed_cycle = True
                    if self.config.guard_ms > 0:
                        self._sleep(self.config.guard_ms / 1000.0)
                    return SettleOutcome(
                        ready=True,
                        method=BASELINE_CONFIRMED_AFTER_RETURN,
                        sample_count=len(samples),
                        completed_active_cycle=True,
                        unfinished_active_cycle=False,
                        last_state=STATE_BASELINE,
                        last_sample=data,
                    )
            elif self._is_wake_state(data):
                consecutive_baseline = 0
                if seen_baseline:
                    seen_nonbaseline_after_baseline = True
            else:
                consecutive_baseline = 0

            self._sleep(self.config.interval_ms / 1000.0)

        if last is not None and self._is_baseline(last):
            method = BASELINE_OBSERVED
            if completed_cycle:
                method = BASELINE_CONFIRMED_AFTER_RETURN
            elif max_consecutive_baseline >= 2:
                method = BASELINE_STABLE_MULTI
            return SettleOutcome(
                ready=True,
                method=method,
                sample_count=len(samples),
                completed_active_cycle=completed_cycle,
                unfinished_active_cycle=False,
                last_state=STATE_BASELINE,
                last_sample=last,
            )

        if last is not None and self._is_wake_state(last):
            return SettleOutcome(
                ready=False,
                method=BASELINE_OBSERVED if seen_baseline else None,
                sample_count=len(samples),
                completed_active_cycle=completed_cycle,
                unfinished_active_cycle=True,
                last_state=self._classify(last),
                last_sample=last,
                error=error,
            )

        if seen_baseline and first_baseline is not None:
            pass

        return SettleOutcome(
            ready=False,
            method=BASELINE_OBSERVED if seen_baseline else None,
            sample_count=len(samples),
            completed_active_cycle=completed_cycle,
            unfinished_active_cycle=bool(seen_nonbaseline_after_baseline),
            last_state=self._classify(last) if last is not None else None,
            last_sample=last,
            error=error,
        )

    def _aggregate(self, scenario: str, reps: list[dict[str, Any]]) -> dict[str, Any]:
        executed = [item for item in reps if item.get("trigger_executed")]
        clean = [item for item in executed if not item.get("contaminated")]
        with_transition = [
            item
            for item in clean
            if item.get("returned_to_baseline")
            and item.get("cycle_kind") in (CYCLE_CANONICAL, CYCLE_TRANSITIONAL)
        ]
        canonical = [
            item for item in clean if item.get("canonical_active_observed")
        ]
        intermediate = [
            item for item in clean if item.get("intermediate_observed")
        ]
        missing_return = [
            item
            for item in clean
            if (
                item.get("intermediate_observed")
                or item.get("canonical_active_observed")
            )
            and not item.get("returned_to_baseline")
        ]
        skipped = [item for item in reps if not item.get("trigger_executed")]

        state_counts = {
            STATE_BASELINE: 0,
            STATE_INTERMEDIATE: 0,
            STATE_ACTIVE: 0,
            STATE_OTHER: 0,
        }
        for item in clean:
            for sample in item.get("samples") or []:
                state = sample.get("state") or STATE_OTHER
                if state not in state_counts:
                    state_counts[STATE_OTHER] += 1
                else:
                    state_counts[state] += 1

        if not executed or not clean or len(with_transition) == 0:
            conclusion = CONCLUSION_INCONCLUSIVE
        elif len(with_transition) >= max(2, (len(clean) + 1) // 2):
            conclusion = CONCLUSION_REPEATABLE
        else:
            conclusion = CONCLUSION_OBSERVED

        return {
            "scenario": scenario,
            "repetitions": len(reps),
            "executed_repetitions": len(executed),
            "skipped_not_executed": len(skipped),
            "clean_repetitions": len(clean),
            "transition_repetitions": len(with_transition),
            "canonical_active_repetitions": len(canonical),
            "intermediate_repetitions": len(intermediate),
            "missing_return_repetitions": len(missing_return),
            "contaminated_repetitions": sum(
                1 for item in reps if item.get("contaminated")
            ),
            "state_counts": state_counts,
            "conclusion": conclusion,
            "repetition_details": reps,
            "uses_sram": False,
            "statistics_note": (
                "Only repetitions with trigger_executed=true are included "
                "in trigger association statistics. "
                "transition_repetitions count complete non-baseline cycles "
                "(canonical or transitional). "
                "'probable trigger' is not assigned from per-scenario "
                "repeatability alone."
            ),
        }

    def _apply_global_conclusions(
        self,
        aggregates: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        if not aggregates:
            metadata["global_conclusion"] = None
            return

        select = aggregates.get("select-only")
        select_transitions = (
            int(select.get("transition_repetitions", 0)) if select else 0
        )
        others = [
            (name, agg)
            for name, agg in aggregates.items()
            if name != "select-only"
        ]
        others_with = [
            name
            for name, agg in others
            if int(agg.get("transition_repetitions", 0)) > 0
        ]
        majority_others = (
            len(others) > 0 and len(others_with) >= max(1, (len(others) + 1) // 2)
        )

        if select_transitions > 0 and majority_others:
            metadata["global_conclusion"] = GLOBAL_RF_CONCLUSION
            for name, agg in aggregates.items():
                if int(agg.get("transition_repetitions", 0)) > 0:
                    agg["conclusion"] = CONCLUSION_GENERAL_RF
                    agg["conclusion_note"] = (
                        "Shared non-baseline cycle pattern with select-only "
                        "and other RF scenarios; association, not confirmed "
                        "causality."
                    )
        else:
            metadata["global_conclusion"] = None

    def _classify(self, data: bytes) -> str:
        if self._is_baseline(data):
            return STATE_BASELINE
        if self._is_intermediate(data):
            return STATE_INTERMEDIATE
        if self._is_active(data):
            return STATE_ACTIVE
        return STATE_OTHER

    @staticmethod
    def _is_baseline(data: bytes | None) -> bool:
        return bool(data) and data[0] == BASELINE_NC and data[6] == BASELINE_NS

    @staticmethod
    def _is_intermediate(data: bytes | None) -> bool:
        return (
            bool(data)
            and data[0] == INTERMEDIATE_NC
            and data[6] == INTERMEDIATE_NS
        )

    @staticmethod
    def _is_active(data: bytes | None) -> bool:
        return bool(data) and data[0] == ACTIVE_NC and data[6] == ACTIVE_NS

    def _is_wake_state(self, data: bytes | None) -> bool:
        return self._is_intermediate(data) or self._is_active(data)

    def _wait_for_tag(self, client: SimpleProtocolClient):
        deadline = time.monotonic() + self.config.wait_tag_s
        while True:
            tag = client.search_tag()
            if tag is not None:
                return tag
            if time.monotonic() >= deadline:
                raise SerialCommunicationError("NFC tag nebyl nalezen.")
            self._sleep(0.12)

    def _reselect(self, client: Any) -> bool:
        try:
            tag = client.search_tag()
        except (ElatecError, SerialCommunicationError) as exc:
            self._emit("rf_error", error=str(exc), rf_operation="SearchTag")
            return False
        if tag is None:
            return False
        self._emit(
            "tag_reselected",
            rf_operation="SearchTag",
            decoded={"uid": tag.id_hex, "role": "preparatory"},
        )
        return True

    def _recover(self, client: Any) -> None:
        self._reselect(client)

    def _timed(self, func: Callable[[], Any]) -> tuple[Any, int]:
        started = self._clock_ns()
        result = func()
        if hasattr(result, "raw") and isinstance(result.raw, (bytes, bytearray)):
            payload = result.raw
        else:
            payload = result
        finished = self._clock_ns()
        return payload, (finished - started) // 1000

    def _elapsed_us(self) -> int:
        return (self._clock_ns() - self._t0_ns) // 1000

    def _emit(
        self,
        event_type: str,
        *,
        rf_operation: str | None = None,
        rf_duration_us: int | None = None,
        raw_hex: str | None = None,
        decoded: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._seq += 1
        event = {
            "seq": self._seq,
            "t_mono_ns": self._clock_ns(),
            "elapsed_us": self._elapsed_us(),
            "wall_time": self._wall_clock(),
            "event_type": event_type,
            "uid": self._uid,
            "rf_operation": rf_operation,
            "rf_duration_us": rf_duration_us,
            "raw_hex": raw_hex,
            "decoded": decoded,
            "error": error,
        }
        event = {key: value for key, value in event.items() if value is not None}
        self._timeline.append(event)
        if error or event_type == "rf_error":
            self._errors.append(event)

    def _row_from_result(self, result: dict[str, Any]) -> dict[str, Any]:
        def _cell(value: Any) -> Any:
            return "" if value is None else value

        return {
            "scenario": result["scenario"],
            "repetition": result["repetition"],
            "trigger_executed": result.get("trigger_executed"),
            "contaminated": result.get("contaminated"),
            "baseline_method": result.get("baseline_method") or "",
            "baseline_sample_count": result.get("baseline_sample_count") or 0,
            "pre_trigger_state": result.get("pre_trigger_state") or "",
            "measurement_interference_possible": result.get(
                "measurement_interference_possible"
            ),
            "baseline_hex": result.get("baseline_hex") or "",
            "rf_operation": result.get("rf_operation") or "",
            "rf_duration_us": _cell(result.get("rf_duration_us")),
            "post_op_hex": result.get("post_op_hex") or "",
            "first_nonbaseline_us": _cell(result.get("first_nonbaseline_us")),
            "first_transition_us": _cell(result.get("first_transition_us")),
            "intermediate_enter_us": _cell(result.get("intermediate_enter_us")),
            "active_enter_us": _cell(result.get("active_enter_us")),
            "return_us": _cell(result.get("return_us")),
            "intermediate_duration_us": _cell(
                result.get("intermediate_duration_us")
            ),
            "canonical_active_duration_us": _cell(
                result.get("canonical_active_duration_us")
            ),
            "total_nonbaseline_window_us": _cell(
                result.get("total_nonbaseline_window_us")
            ),
            "active_window_us": _cell(result.get("active_window_us")),
            "transition_count": result.get("transition_count") or 0,
            "intermediate_observed": result.get("intermediate_observed"),
            "canonical_active_observed": result.get("canonical_active_observed"),
            "active_observed": result.get("active_observed"),
            "returned_to_baseline": result.get("returned_to_baseline"),
            "cycle_kind": result.get("cycle_kind") or "",
            "verdict": result.get("verdict"),
            "errors": "|".join(result.get("errors") or []),
            "note": result.get("note") or "",
        }

    def _write_outputs(
        self,
        directory: Path,
        metadata: dict[str, Any],
        aggregates: dict[str, Any],
    ) -> None:
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with (directory / "timeline.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for event in self._timeline:
                handle.write(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
        with (directory / "scenarios.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            fieldnames = [
                "scenario",
                "repetition",
                "trigger_executed",
                "contaminated",
                "baseline_method",
                "baseline_sample_count",
                "pre_trigger_state",
                "measurement_interference_possible",
                "baseline_hex",
                "rf_operation",
                "rf_duration_us",
                "post_op_hex",
                "first_nonbaseline_us",
                "first_transition_us",
                "intermediate_enter_us",
                "active_enter_us",
                "return_us",
                "intermediate_duration_us",
                "canonical_active_duration_us",
                "total_nonbaseline_window_us",
                "active_window_us",
                "transition_count",
                "intermediate_observed",
                "canonical_active_observed",
                "active_observed",
                "returned_to_baseline",
                "cycle_kind",
                "verdict",
                "errors",
                "note",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in self._rows:
                writer.writerow(row)
        if self._errors:
            with (directory / "errors.jsonl").open(
                "w", encoding="utf-8", newline="\n"
            ) as handle:
                for event in self._errors:
                    handle.write(
                        json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
        (directory / "report.txt").write_text(
            self._build_report(metadata, aggregates),
            encoding="utf-8",
        )

    def _build_report(
        self,
        metadata: dict[str, Any],
        aggregates: dict[str, Any],
    ) -> str:
        lines = [
            "Trigger Analysis — souhrn",
            "=========================",
            "",
            "Režim: READ-ONLY, bez SRAM",
            "Stavy: baseline 0x19/0x01, intermediate 0x7C/0x41, active 0x7C/0x29",
            "Baseline: first-sample; multi-read není povinný.",
            "active_window_us = total_nonbaseline_window_us (compat).",
            "SearchTag rf_duration_us = transport/API duration, ne čistý RF frame.",
            "Závěry jsou asociační, ne confirmed trigger.",
            f"Port: {metadata.get('port')}",
            f"UID: {metadata.get('uid')}",
            f"GET_VERSION: {metadata.get('get_version')}",
            "",
            "Scénáře:",
        ]
        for scenario, aggregate in aggregates.items():
            lines.append(
                f"  - {scenario}: {aggregate.get('conclusion')} "
                f"(executed {aggregate.get('executed_repetitions')}/"
                f"{aggregate.get('repetitions')}, "
                f"transitions {aggregate.get('transition_repetitions')}, "
                f"canonical {aggregate.get('canonical_active_repetitions')}, "
                f"intermediate {aggregate.get('intermediate_repetitions')}, "
                f"skipped {aggregate.get('skipped_not_executed')})"
            )
            counts = aggregate.get("state_counts") or {}
            if counts:
                lines.append(
                    "      states: "
                    + ", ".join(f"{key}={value}" for key, value in counts.items())
                )
            if aggregate.get("skipped_not_executed"):
                reasons = [
                    item.get("note")
                    for item in aggregate.get("repetition_details", [])
                    if not item.get("trigger_executed")
                ]
                for reason in reasons[:3]:
                    if reason:
                        lines.append(f"      skip reason: {reason}")
        global_conclusion = metadata.get("global_conclusion")
        lines.append("")
        if global_conclusion:
            lines.append(f"Global: {global_conclusion}")
            lines.append("")
        lines.append(metadata.get("isolation_note", ""))
        lines.append("")
        return "\n".join(lines) + "\n"

    def _rename(self, directory: Path) -> Path:
        if not self._uid:
            return directory
        uid = self._uid.upper()
        parts = directory.name.rsplit("_", 1)
        if len(parts) == 2 and parts[1].upper() == "PENDING":
            target_name = f"{parts[0]}_{uid}"
        else:
            target_name = capture_dir_name(self._uid)
        target = directory.parent / target_name
        suffix = 1
        while target.exists():
            target = directory.parent / f"{target_name}_{suffix}"
            suffix += 1
        try:
            directory.rename(target)
            return target
        except OSError:
            return directory
