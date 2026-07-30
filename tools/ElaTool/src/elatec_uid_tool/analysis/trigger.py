from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
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
ACTIVE_NC = 0x7C
ACTIVE_NS = 0x29

SCENARIO_IDS = (
    "select-only",
    "get-version",
    "read-page-00",
    "read-application-block",
    "read-session",
    "get-version-then-session",
    "repeated-session-only",
)

CONCLUSION_OBSERVED = "observed association"
CONCLUSION_REPEATABLE = "repeatable association"
CONCLUSION_PROBABLE = "probable trigger"
CONCLUSION_INCONCLUSIVE = "inconclusive"


@dataclass
class TriggerConfig:
    port: str
    scenarios: list[str] = field(default_factory=lambda: list(SCENARIO_IDS))
    duration_s: float = 2.0
    interval_ms: float = 50.0
    settle_ms: float = 1500.0
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
            "schema": 1,
            "tool": "trigger-analysis",
            "read_only": True,
            "uses_sram": False,
            "started_at": self._wall_clock(),
            "port": config.port,
            "duration_s": config.duration_s,
            "interval_ms": config.interval_ms,
            "settle_ms": config.settle_ms,
            "repetitions": config.repetitions,
            "scenarios": list(config.scenarios),
            "baseline": {"NC_REG": BASELINE_NC, "NS_REG": BASELINE_NS},
            "active": {"NC_REG": ACTIVE_NC, "NS_REG": ACTIVE_NS},
            "isolation_note": (
                "Best-effort settle/reselect only. Not an isolated RF field; "
                "do not treat results as confirmed causality."
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
        config = self.config
        reps: list[dict[str, Any]] = []
        for repetition in range(1, config.repetitions + 1):
            reps.append(self._run_repetition(ntag, scenario, repetition))
        aggregate = self._aggregate(scenario, reps)
        if self.config.verbose:
            print(
                f"[aggregate] {scenario}: {aggregate['conclusion']} "
                f"(clean={aggregate['clean_repetitions']}/"
                f"{aggregate['repetitions']}, "
                f"transitions={aggregate['transition_repetitions']})"
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

        settled, settle_samples = self._settle_to_baseline(ntag)
        reselected = self._reselect(ntag.client)
        baseline, baseline_stable, contaminated = self._read_baseline(ntag)

        result: dict[str, Any] = {
            "scenario": scenario,
            "repetition": repetition,
            "settled": settled,
            "reselected": reselected,
            "baseline_hex": baseline.hex(" ").upper() if baseline else None,
            "baseline_stable": baseline_stable,
            "contaminated": contaminated or not settled or not baseline_stable,
            "rf_operation": scenario,
            "rf_duration_us": None,
            "post_op_hex": None,
            "first_transition_us": None,
            "return_us": None,
            "active_window_us": None,
            "transition_count": 0,
            "active_observed": False,
            "returned_to_baseline": False,
            "errors": [],
            "verdict": CONCLUSION_INCONCLUSIVE,
            "samples": [],
        }

        if result["contaminated"]:
            result["verdict"] = CONCLUSION_INCONCLUSIVE
            result["note"] = "Baseline not stable before RF action."
            self._rows.append(self._row_from_result(result))
            self._emit(
                "scenario_finished",
                decoded={
                    "scenario": scenario,
                    "repetition": repetition,
                    "verdict": result["verdict"],
                    "contaminated": True,
                },
            )
            return result

        try:
            op_data, op_us = self._execute_scenario_action(ntag, scenario)
            result["rf_duration_us"] = op_us
            self._emit(
                "scenario_action",
                rf_operation=scenario,
                rf_duration_us=op_us,
                raw_hex=op_data.hex(" ").upper() if isinstance(op_data, (bytes, bytearray)) else None,
                decoded={"scenario": scenario, "repetition": repetition},
            )
        except (ElatecError, SerialCommunicationError, ValueError) as exc:
            result["errors"].append(str(exc))
            self._emit("rf_error", error=str(exc), rf_operation=scenario)
            self._recover(ntag.client)
            result["verdict"] = CONCLUSION_INCONCLUSIVE
            self._rows.append(self._row_from_result(result))
            return result

        post, post_us = self._timed(ntag.read_session_registers)
        result["post_op_hex"] = post.hex(" ").upper()
        action_elapsed = self._elapsed_us()
        self._emit(
            "session_sample",
            rf_operation="FAST_READ 3A EC ED",
            rf_duration_us=post_us,
            raw_hex=result["post_op_hex"],
            decoded={"phase": "post_action", "scenario": scenario},
        )

        samples = [
            {
                "elapsed_us": action_elapsed,
                "raw_hex": result["post_op_hex"],
                "nc": post[0],
                "ns": post[6],
                "state": self._classify(post),
            }
        ]

        previous = post
        transitions = 0
        first_transition_us = None
        return_us = None
        if self._is_active(post) and self._is_baseline(baseline):
            transitions = 1
            first_transition_us = action_elapsed
            result["active_observed"] = True

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
                self._emit("rf_error", error=str(exc), rf_operation="FAST_READ 3A EC ED")
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
                }
            )
            self._emit(
                "session_sample",
                rf_operation="FAST_READ 3A EC ED",
                rf_duration_us=rf_us,
                raw_hex=current.hex(" ").upper(),
                decoded={"phase": "monitor", "scenario": scenario, "state": state},
            )

            if previous != current:
                transitions += 1
                if (
                    first_transition_us is None
                    and self._is_baseline(previous)
                    and self._is_active(current)
                ):
                    first_transition_us = elapsed
                    result["active_observed"] = True
                if (
                    result["active_observed"]
                    and return_us is None
                    and self._is_active(previous)
                    and self._is_baseline(current)
                ):
                    return_us = elapsed
                    result["returned_to_baseline"] = True
            previous = current
            next_sample += interval_ns
            if next_sample < self._clock_ns():
                next_sample = self._clock_ns() + interval_ns

        result["samples"] = samples
        result["transition_count"] = transitions
        result["first_transition_us"] = first_transition_us
        result["return_us"] = return_us
        if first_transition_us is not None and return_us is not None:
            result["active_window_us"] = return_us - first_transition_us
        elif result["active_observed"] and return_us is None:
            result["note"] = "Active state observed but no return within duration."
            result["verdict"] = CONCLUSION_INCONCLUSIVE
        if result["active_observed"] and result["returned_to_baseline"]:
            result["verdict"] = CONCLUSION_OBSERVED
        elif result["active_observed"]:
            result["verdict"] = CONCLUSION_INCONCLUSIVE
        else:
            result["verdict"] = CONCLUSION_INCONCLUSIVE
            result.setdefault("note", "No baseline→active transition observed.")

        if self.config.verbose:
            print(
                f"[{scenario} #{repetition}] "
                f"active={result['active_observed']} "
                f"return={result['returned_to_baseline']} "
                f"transitions={transitions} "
                f"verdict={result['verdict']}"
            )

        self._rows.append(self._row_from_result(result))
        self._emit(
            "scenario_finished",
            decoded={
                "scenario": scenario,
                "repetition": repetition,
                "verdict": result["verdict"],
                "active_observed": result["active_observed"],
                "contaminated": result["contaminated"],
            },
        )
        return result

    def _execute_scenario_action(
        self,
        ntag: NtagI2CPlus,
        scenario: str,
    ) -> tuple[Any, int]:
        # Guard: never touch SRAM helpers.
        if hasattr(ntag, "read_sram") and scenario == "read-sram":
            self._forbidden_sram_ops += 1
            raise RuntimeError("SRAM is forbidden in trigger analysis.")

        if scenario == "select-only":
            started = self._clock_ns()
            tag = ntag.client.search_tag()
            finished = self._clock_ns()
            if tag is None:
                raise SerialCommunicationError("select-only: SearchTag nenašel tag.")
            return tag.id_bytes, (finished - started) // 1000

        if scenario == "get-version":
            return self._timed(ntag.get_version)

        if scenario == "read-page-00":
            return self._timed(lambda: ntag.read_block(0x00))

        if scenario == "read-application-block":
            return self._timed(
                lambda: ntag.read_eeprom_range(
                    EEPROM_WATCH_START_PAGE,
                    EEPROM_WATCH_END_PAGE,
                )
            )

        if scenario == "read-session":
            return self._timed(ntag.read_session_registers)

        if scenario == "get-version-then-session":
            started = self._clock_ns()
            version = ntag.get_version()
            session = ntag.read_session_registers()
            finished = self._clock_ns()
            return version.raw + session, (finished - started) // 1000

        if scenario == "repeated-session-only":
            # Action phase intentionally empty; monitoring loop performs repeats.
            return b"", 0

        raise ValueError(f"Neznámý scénář: {scenario}")

    def _settle_to_baseline(self, ntag: NtagI2CPlus) -> tuple[bool, list[bytes]]:
        deadline = self._clock_ns() + int(self.config.settle_ms * 1_000_000)
        samples: list[bytes] = []
        while self._clock_ns() < deadline:
            try:
                data, _rf = self._timed(ntag.read_session_registers)
            except (ElatecError, SerialCommunicationError):
                self._recover(ntag.client)
                self._sleep(self.config.interval_ms / 1000.0)
                continue
            samples.append(data)
            self._emit(
                "session_sample",
                rf_operation="FAST_READ 3A EC ED",
                raw_hex=data.hex(" ").upper(),
                decoded={"phase": "settle", "state": self._classify(data)},
            )
            if self._is_baseline(data):
                # Require a second confirming sample.
                self._sleep(self.config.interval_ms / 1000.0)
                try:
                    confirm, _ = self._timed(ntag.read_session_registers)
                except (ElatecError, SerialCommunicationError):
                    continue
                samples.append(confirm)
                if self._is_baseline(confirm):
                    return True, samples
            self._sleep(self.config.interval_ms / 1000.0)
        return False, samples

    def _read_baseline(self, ntag: NtagI2CPlus) -> tuple[bytes | None, bool, bool]:
        try:
            first, _ = self._timed(ntag.read_session_registers)
            self._sleep(self.config.interval_ms / 1000.0)
            second, _ = self._timed(ntag.read_session_registers)
        except (ElatecError, SerialCommunicationError) as exc:
            self._emit("rf_error", error=str(exc), rf_operation="FAST_READ 3A EC ED")
            return None, False, True
        stable = first == second
        contaminated = not (stable and self._is_baseline(first))
        self._emit(
            "baseline_sample",
            raw_hex=first.hex(" ").upper(),
            decoded={
                "stable": stable,
                "contaminated": contaminated,
                "state": self._classify(first),
            },
        )
        return first, stable, contaminated

    def _aggregate(self, scenario: str, reps: list[dict[str, Any]]) -> dict[str, Any]:
        clean = [item for item in reps if not item.get("contaminated")]
        with_transition = [
            item
            for item in clean
            if item.get("active_observed") and item.get("returned_to_baseline")
        ]
        missing_return = [
            item
            for item in clean
            if item.get("active_observed") and not item.get("returned_to_baseline")
        ]

        if not clean:
            conclusion = CONCLUSION_INCONCLUSIVE
        elif len(with_transition) == 0:
            conclusion = CONCLUSION_INCONCLUSIVE
        elif len(with_transition) == len(clean) and len(clean) >= 3:
            conclusion = CONCLUSION_PROBABLE
        elif len(with_transition) >= max(2, (len(clean) + 1) // 2):
            conclusion = CONCLUSION_REPEATABLE
        else:
            conclusion = CONCLUSION_OBSERVED

        return {
            "scenario": scenario,
            "repetitions": len(reps),
            "clean_repetitions": len(clean),
            "transition_repetitions": len(with_transition),
            "missing_return_repetitions": len(missing_return),
            "contaminated_repetitions": sum(1 for item in reps if item.get("contaminated")),
            "conclusion": conclusion,
            "repetition_details": reps,
            "uses_sram": False,
        }

    def _classify(self, data: bytes) -> str:
        if self._is_baseline(data):
            return "baseline"
        if self._is_active(data):
            return "active"
        return "other"

    @staticmethod
    def _is_baseline(data: bytes | None) -> bool:
        return bool(data) and data[0] == BASELINE_NC and data[6] == BASELINE_NS

    @staticmethod
    def _is_active(data: bytes | None) -> bool:
        return bool(data) and data[0] == ACTIVE_NC and data[6] == ACTIVE_NS

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
            decoded={"uid": tag.id_hex},
        )
        return True

    def _recover(self, client: Any) -> None:
        self._reselect(client)

    def _timed(self, func: Callable[[], Any]) -> tuple[Any, int]:
        started = self._clock_ns()
        result = func()
        # Unwrap NtagVersion
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
        return {
            "scenario": result["scenario"],
            "repetition": result["repetition"],
            "contaminated": result["contaminated"],
            "baseline_hex": result.get("baseline_hex") or "",
            "rf_operation": result.get("rf_operation") or "",
            "rf_duration_us": result.get("rf_duration_us") or "",
            "post_op_hex": result.get("post_op_hex") or "",
            "first_transition_us": result.get("first_transition_us") or "",
            "return_us": result.get("return_us") or "",
            "active_window_us": result.get("active_window_us") or "",
            "transition_count": result.get("transition_count") or 0,
            "active_observed": result.get("active_observed"),
            "returned_to_baseline": result.get("returned_to_baseline"),
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
        with (directory / "timeline.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for event in self._timeline:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        with (directory / "scenarios.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            fieldnames = [
                "scenario",
                "repetition",
                "contaminated",
                "baseline_hex",
                "rf_operation",
                "rf_duration_us",
                "post_op_hex",
                "first_transition_us",
                "return_us",
                "active_window_us",
                "transition_count",
                "active_observed",
                "returned_to_baseline",
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
                f"(clean {aggregate.get('clean_repetitions')}/"
                f"{aggregate.get('repetitions')}, "
                f"transitions {aggregate.get('transition_repetitions')})"
            )
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
