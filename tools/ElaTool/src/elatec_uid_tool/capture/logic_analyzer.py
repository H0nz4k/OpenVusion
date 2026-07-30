from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    SESSION_REGISTER_NAMES,
    SRAM_RF_END_PAGE,
    SRAM_RF_START_PAGE,
    SRAM_SIZE_BYTES,
    NtagI2CPlus,
)
from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient
from .changes import eeprom_changes, session_changes, sram_changes
from .models import CaptureEvent, bytes_to_hex, safe_ascii_preview
from .writer import (
    DEFAULT_CAPTURE_ROOT,
    CaptureWriter,
    capture_dir_name,
    create_capture_dir,
)


@dataclass
class LogicAnalyzerConfig:
    port: str
    duration_s: float = 5.0
    interval_ms: float = 50.0
    output_dir: Path = field(default_factory=lambda: DEFAULT_CAPTURE_ROOT)
    watch_eeprom: bool = False
    verbose: bool = False
    timeout: float = 2.0
    wait_tag_s: float = 15.0
    poll_interval_s: float = 0.12


@dataclass
class LogicAnalyzerResult:
    directory: Path
    uid: str | None
    event_count: int
    error_count: int
    sample_cycles: int
    partial: bool
    metadata: dict[str, Any]


class LogicAnalyzerCapture:
    """Read-only capture session + SRAM (+ optional EEPROM) na jedné ose."""

    def __init__(
        self,
        config: LogicAnalyzerConfig,
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
        self._writer: CaptureWriter | None = None
        self._uid: str | None = None
        self._sample_cycles = 0
        self._session_change_count = 0
        self._sram_change_count = 0
        self._eeprom_change_count = 0
        self._unique_session: set[str] = set()
        self._unique_sram: set[str] = set()
        self._partial = False
        self._finish_reason = "completed"

    def run(self) -> LogicAnalyzerResult:
        config = self.config
        output_root = Path(config.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)

        started_wall = self._wall_clock()
        metadata: dict[str, Any] = {
            "schema": 1,
            "tool": "nfc-logic-analyzer",
            "read_only": True,
            "started_at": started_wall,
            "port": config.port,
            "duration_s": config.duration_s,
            "interval_ms": config.interval_ms,
            "watch_eeprom": config.watch_eeprom,
            "sampling_strategy": "session -> sram"
            + (" -> eeprom[0x30-0x37]" if config.watch_eeprom else ""),
            "timing_note": (
                "Společná časová osa sekvenčně provedených měření; "
                "session a SRAM nejsou simultánní."
            ),
            "sram_rf_pages": {
                "start": SRAM_RF_START_PAGE,
                "end": SRAM_RF_END_PAGE,
                "size_bytes": SRAM_SIZE_BYTES,
                "source": "NXP NT3H2111_2211 datasheet (pass-through mapping)",
                "local_verification": "pending",
            },
            "rf_commands": [
                "SearchTag",
                "GET_VERSION 60",
                "FAST_READ 3A EC ED",
                "FAST_READ 3A F0 FF",
            ],
        }
        if config.watch_eeprom:
            metadata["rf_commands"].append("FAST_READ 3A 30 37")

        directory = create_capture_dir(
            output_root,
            "pending",
            when=datetime.now(),
        )
        writer = CaptureWriter(directory)
        self._writer = writer
        self._t0_ns = self._clock_ns()

        client = self._client_factory(config.port, config.timeout)
        entered = False

        try:
            enter = getattr(client, "__enter__", None)
            if callable(enter):
                client = enter()
                entered = True

            self._emit(
                "capture_started",
                decoded={
                    "port": config.port,
                    "duration_s": config.duration_s,
                    "interval_ms": config.interval_ms,
                    "watch_eeprom": config.watch_eeprom,
                    "capture_dir": str(directory),
                },
            )

            tag = self._wait_for_tag(client)
            self._uid = tag.id_hex
            self._emit(
                "tag_detected",
                uid=self._uid,
                rf_operation="SearchTag",
                decoded={
                    "tag_type": tag.tag_type,
                    "id_bit_count": tag.id_bit_count,
                    "uid": self._uid,
                },
            )

            ntag = NtagI2CPlus(client)
            version, rf_us = self._timed(ntag.get_version)
            self._emit(
                "get_version",
                uid=self._uid,
                rf_operation="GET_VERSION 60",
                rf_duration_us=rf_us,
                raw_hex=bytes_to_hex(version.raw),
                decoded={
                    "raw": bytes_to_hex(version.raw),
                    "is_ntag_i2c_plus_1k": version.is_ntag_i2c_plus_1k,
                },
            )
            metadata["uid"] = self._uid
            metadata["get_version"] = bytes_to_hex(version.raw)
            metadata["tag_type"] = tag.tag_type
            metadata["id_bit_count"] = tag.id_bit_count
            metadata["capture_dir"] = str(directory)

            self._run_sampling_loop(ntag, writer, metadata)
            self._finish_reason = "completed"
        except BaseException as exc:
            self._partial = True
            self._finish_reason = type(exc).__name__
            self._emit(
                "rf_error",
                uid=self._uid,
                error=str(exc),
                decoded={"exception": type(exc).__name__},
            )
            raise
        finally:
            try:
                self._emit(
                    "capture_finished",
                    uid=self._uid,
                    decoded={
                        "reason": self._finish_reason,
                        "partial": self._partial,
                        "sample_cycles": self._sample_cycles,
                    },
                )
            except Exception:
                pass
            metadata.update(self._summary_metadata())
            metadata["finished_at"] = self._wall_clock()
            metadata["partial"] = self._partial
            metadata["uid"] = self._uid
            try:
                writer.write_metadata(metadata)
                writer.write_report(self._build_report(metadata))
            finally:
                writer.close()
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

            directory = self._finalize_directory_name(directory)

        return LogicAnalyzerResult(
            directory=directory,
            uid=self._uid,
            event_count=writer.event_count,
            error_count=writer.error_count,
            sample_cycles=self._sample_cycles,
            partial=self._partial,
            metadata=metadata,
        )

    def run_safe(self) -> LogicAnalyzerResult:
        """Stejné jako run(), ale při chybě vrátí partial výsledek."""
        try:
            return self.run()
        except BaseException as exc:
            if self._writer is None:
                raise
            return LogicAnalyzerResult(
                directory=self._writer.directory,
                uid=self._uid,
                event_count=self._writer.event_count,
                error_count=self._writer.error_count,
                sample_cycles=self._sample_cycles,
                partial=True,
                metadata={
                    "partial": True,
                    "error": str(exc),
                    "finish_reason": self._finish_reason,
                    "uid": self._uid,
                },
            )

    def _finalize_directory_name(self, directory: Path) -> Path:
        """Po uzavření souborů přejmenuje pending adresář na UID."""
        if not self._uid:
            return directory
        uid = self._uid.upper()
        if directory.name.upper().endswith(f"_{uid}"):
            return directory

        # Expected shape: YYYY-MM-DD_HH-MM-SS_PENDING
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
            if self._writer is not None:
                self._writer.directory = target
            return target
        except OSError:
            return directory

    def _wait_for_tag(self, client: SimpleProtocolClient):
        deadline = time.monotonic() + self.config.wait_tag_s
        while True:
            tag = client.search_tag()
            if tag is not None:
                return tag
            if time.monotonic() >= deadline:
                raise SerialCommunicationError(
                    "NFC tag nebyl nalezen v časovém limitu. Přilož štítek ke čtečce."
                )
            self._sleep(self.config.poll_interval_s)

    def _run_sampling_loop(
        self,
        ntag: NtagI2CPlus,
        writer: CaptureWriter,
        metadata: dict[str, Any],
    ) -> None:
        config = self.config
        interval_ns = int(config.interval_ms * 1_000_000)
        duration_ns = int(config.duration_s * 1_000_000_000)
        next_sample_ns = self._clock_ns()

        previous_session: bytes | None = None
        previous_sram: bytes | None = None
        previous_eeprom: bytes | None = None
        initial_eeprom: bytes | None = None
        tag_lost = False

        while True:
            now_ns = self._clock_ns()
            if now_ns - self._t0_ns >= duration_ns:
                break

            if now_ns < next_sample_ns:
                delay_s = (next_sample_ns - now_ns) / 1_000_000_000
                if delay_s > 0:
                    self._sleep(delay_s)

            cycle_started = self._clock_ns()
            self._sample_cycles += 1

            session, rf_us = self._try_read(
                "FAST_READ 3A EC ED",
                ntag.read_session_registers,
            )
            if session is None and not tag_lost:
                tag_lost = True
                self._emit(
                    "tag_lost",
                    uid=self._uid,
                    error="Selhalo čtení session registrů.",
                )
            elif session is not None:
                tag_lost = False
                self._unique_session.add(session.hex(" ").upper())
                decoded_hex = {
                    name: f"0x{value:02X}"
                    for name, value in zip(SESSION_REGISTER_NAMES, session)
                }
                changes = None
                event_type = "session_sample"
                if previous_session is not None:
                    changes = session_changes(previous_session, session)
                    if changes["changed"]:
                        event_type = "session_changed"
                        self._session_change_count += 1
                self._emit(
                    event_type,
                    uid=self._uid,
                    rf_operation="FAST_READ 3A EC ED",
                    rf_duration_us=rf_us,
                    raw_hex=bytes_to_hex(session),
                    decoded={"registers": decoded_hex, "bytes": list(session)},
                    changes=changes,
                )
                if config.verbose and (changes is None or changes["changed"]):
                    print(
                        f"[session] +{self._elapsed_us() / 1000:.1f} ms  "
                        f"NC=0x{session[0]:02X} NS=0x{session[6]:02X}  "
                        f"{bytes_to_hex(session)}"
                    )
                previous_session = session

            sram, rf_us = self._try_read("FAST_READ 3A F0 FF", ntag.read_sram)
            if sram is not None:
                tag_lost = False
                self._unique_sram.add(sram.hex(" ").upper())
                changes = None
                event_type = "sram_sample"
                if previous_sram is not None:
                    changes = sram_changes(previous_sram, sram)
                    if changes["changed"]:
                        event_type = "sram_changed"
                        self._sram_change_count += 1
                self._emit(
                    event_type,
                    uid=self._uid,
                    rf_operation="FAST_READ 3A F0 FF",
                    rf_duration_us=rf_us,
                    raw_hex=bytes_to_hex(sram),
                    decoded={
                        "size": len(sram),
                        "ascii_preview": safe_ascii_preview(sram),
                        "all_zero": sram == bytes(SRAM_SIZE_BYTES),
                    },
                    changes=changes,
                )
                if config.verbose and (changes is None or changes["changed"]):
                    preview = bytes_to_hex(sram) or ""
                    print(
                        f"[sram]    +{self._elapsed_us() / 1000:.1f} ms  "
                        f"len={len(sram)} zero={sram == bytes(SRAM_SIZE_BYTES)}  "
                        f"{preview[:47]}..."
                    )
                previous_sram = sram

            if config.watch_eeprom:
                eeprom, rf_us = self._try_read(
                    "FAST_READ 3A 30 37",
                    lambda: ntag.read_eeprom_range(
                        EEPROM_WATCH_START_PAGE,
                        EEPROM_WATCH_END_PAGE,
                    ),
                )
                if eeprom is not None:
                    if initial_eeprom is None:
                        initial_eeprom = eeprom
                        writer.write_binary("initial_eeprom.bin", eeprom)
                    changes = None
                    event_type = "eeprom_sample"
                    if previous_eeprom is not None:
                        changes = eeprom_changes(
                            previous_eeprom,
                            eeprom,
                            start_page=EEPROM_WATCH_START_PAGE,
                        )
                        if changes["changed"]:
                            event_type = "eeprom_changed"
                            self._eeprom_change_count += 1
                    self._emit(
                        event_type,
                        uid=self._uid,
                        rf_operation="FAST_READ 3A 30 37",
                        rf_duration_us=rf_us,
                        raw_hex=bytes_to_hex(eeprom),
                        decoded={
                            "start_page": EEPROM_WATCH_START_PAGE,
                            "end_page": EEPROM_WATCH_END_PAGE,
                        },
                        changes=changes,
                    )
                    previous_eeprom = eeprom

            next_sample_ns += interval_ns
            current_ns = self._clock_ns()
            if config.verbose:
                lag_us = max(0, (current_ns - (cycle_started + interval_ns)) // 1000)
                if lag_us:
                    print(f"[lag]     cycle delayed by {lag_us} us")
            if next_sample_ns < current_ns:
                next_sample_ns = current_ns + interval_ns

        if previous_eeprom is not None:
            writer.write_binary("final_eeprom.bin", previous_eeprom)
            metadata["eeprom_watched"] = True

    def _try_read(
        self,
        operation: str,
        func: Callable[[], bytes],
    ) -> tuple[bytes | None, int | None]:
        try:
            data, rf_us = self._timed(func)
            return data, rf_us
        except (ElatecError, SerialCommunicationError, ValueError) as exc:
            self._handle_rf_error(operation, exc)
            return None, None

    def _timed(self, func: Callable[[], Any]) -> tuple[Any, int]:
        started = self._clock_ns()
        result = func()
        finished = self._clock_ns()
        return result, (finished - started) // 1000

    def _elapsed_us(self) -> int:
        if not self._t0_ns:
            return 0
        return (self._clock_ns() - self._t0_ns) // 1000

    def _emit(
        self,
        event_type: str,
        *,
        uid: str | None = None,
        rf_operation: str | None = None,
        rf_duration_us: int | None = None,
        raw_hex: str | None = None,
        decoded: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> CaptureEvent:
        if self._writer is None:
            raise RuntimeError("Writer není připraven.")
        self._seq += 1
        event = CaptureEvent(
            seq=self._seq,
            t_mono_ns=self._clock_ns(),
            elapsed_us=self._elapsed_us(),
            wall_time=self._wall_clock(),
            event_type=event_type,
            uid=uid,
            rf_operation=rf_operation,
            rf_duration_us=rf_duration_us,
            raw_hex=raw_hex,
            decoded=decoded,
            changes=changes,
            error=error,
        )
        self._writer.write_event(event)
        return event

    def _handle_rf_error(self, operation: str, exc: Exception) -> None:
        self._emit(
            "rf_error",
            uid=self._uid,
            rf_operation=operation,
            error=str(exc),
            decoded={"exception": type(exc).__name__},
        )
        if self.config.verbose:
            print(f"[error]   {operation}: {exc}")

    def _summary_metadata(self) -> dict[str, Any]:
        return {
            "sample_cycles": self._sample_cycles,
            "session_changes": self._session_change_count,
            "sram_changes": self._sram_change_count,
            "eeprom_changes": self._eeprom_change_count,
            "unique_session_states": len(self._unique_session),
            "unique_sram_states": len(self._unique_sram),
            "finish_reason": self._finish_reason,
        }

    def _build_report(self, metadata: dict[str, Any]) -> str:
        lines = [
            "NFC Logic Analyzer — souhrn",
            "===========================",
            "",
            "Režim: read-only (GET_VERSION / FAST_READ / READ)",
            "Časování: společná osa sekvenčně provedených měření",
            f"Port: {metadata.get('port')}",
            f"UID: {metadata.get('uid')}",
            f"GET_VERSION: {metadata.get('get_version')}",
            f"Duration: {metadata.get('duration_s')} s",
            f"Interval: {metadata.get('interval_ms')} ms",
            f"Strategy: {metadata.get('sampling_strategy')}",
            "",
            f"Sample cycles: {metadata.get('sample_cycles', 0)}",
            f"Session changes: {metadata.get('session_changes', 0)}",
            f"SRAM changes: {metadata.get('sram_changes', 0)}",
            f"EEPROM changes: {metadata.get('eeprom_changes', 0)}",
            f"Unique session states: {metadata.get('unique_session_states', 0)}",
            f"Unique SRAM states: {metadata.get('unique_sram_states', 0)}",
            f"Partial capture: {metadata.get('partial', False)}",
            f"Finish reason: {metadata.get('finish_reason')}",
            "",
            "SRAM RF mapping: pages 0xF0–0xFF (64 B) per NXP datasheet",
            "pass-through mode. Local physical verification still pending.",
            "",
            "Hypotéza (ne fakt): elektronika štítku může při RF aktivitě",
            "měnit session registry a v aktivním okně používat SRAM / pass-through.",
            "",
        ]
        if self._writer is not None:
            lines.append(f"Capture dir: {self._writer.directory}")
            lines.append(f"timeline.jsonl events: {self._writer.event_count}")
            lines.append(f"errors: {self._writer.error_count}")
        lines.append("")
        return "\n".join(lines) + "\n"


def run_logic_analyzer(config: LogicAnalyzerConfig) -> LogicAnalyzerResult:
    return LogicAnalyzerCapture(config).run()
