from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    SESSION_REGISTER_NAMES,
    NtagI2CPlus,
)
from ..protocol import (
    ElatecError,
    ProtocolError,
    SerialCommunicationError,
    SimpleProtocolClient,
    TagRead,
)

from .persist import CaptureStore, make_capture_dir
from .raw_trace import RawSerialTracer
from .retry import AttemptRecord, run_with_retry
from .status import (
    OverallStatus,
    PhaseStatus,
    aggregate_attempt_statuses,
    classify_exception,
    compute_overall,
)

EventCallback = Callable[[str, dict[str, Any]], None]
PhaseCallback = Callable[[str, str], None]
UidGate = Callable[[str], bool]

FULL_DUMP_START_PAGE = 0x00
FULL_DUMP_END_PAGE = 0xE1
FULL_DUMP_CHUNK_PAGES = 16


@dataclass
class ProbeConfig:
    port: str
    output: Path
    raw_trace: bool = False
    tag_timeout: float = 60.0
    retry_count: int = 3
    retry_delay_ms: float = 150.0
    session_seconds: float = 2.0
    session_interval_ms: float = 50.0
    poll_interval_seconds: float = 0.25
    confirm_reads: int = 3
    skip_eeprom: bool = False
    skip_application: bool = False
    skip_session: bool = False
    verbose: bool = False
    quiet: bool = False
    handshake_timeout: float = 2.0


@dataclass
class ProbeResult:
    overall: OverallStatus
    uid: str | None
    output_dir: Path
    phase_statuses: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    port_closed: bool = False
    duplicate: bool = False
    aborted: bool = False


class CaptureProbe:
    """One process, one COM port, one tag, one read-only capture.

    Shared by PCSniff (CLI) and HWSniff (UI orchestration). Directory stays
    ``*_UID-pending`` until serial/tracer close; then rename to ``*_UID-<uid>``.
    """

    def __init__(
        self,
        config: ProbeConfig,
        *,
        client_factory: Callable[[str, float], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        stdout: TextIO | None = None,
        stop_event: threading.Event | None = None,
        on_event: EventCallback | None = None,
        on_phase: PhaseCallback | None = None,
        uid_gate: UidGate | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or (
            lambda port, t: SimpleProtocolClient(port, timeout=t)
        )
        self._sleep = sleep
        self._stdout = stdout
        self._stop = stop_event
        self._on_event = on_event
        self._on_phase = on_phase
        self._uid_gate = uid_gate
        self._uid: str | None = None
        self._tag_type: int | None = None
        self._ntag_capable = False
        self._store: CaptureStore | None = None
        self._client: Any = None
        self._tracer: RawSerialTracer | None = None
        self._port_closed = False
        self._capture_ran = False
        self._duplicate = False
        self._aborted = False
        self._phase_index = 0
        self._phase_total = 7

    def run(self) -> ProbeResult:
        store = CaptureStore(make_capture_dir(self.config.output, uid=None))
        self._store = store
        store.update_summary(com_port=self.config.port, working_dir=str(store.root))
        self._emit("Čekám na tag...")
        store.append_event("probe_started", port=self.config.port)

        overall = OverallStatus.FAILED
        try:
            self._client = self._client_factory(
                self.config.port, self.config.handshake_timeout
            )
            self._client.__enter__()
            if self.config.raw_trace:
                self._attach_raw_trace(store.root / "raw_serial.jsonl")

            self._run_reader_info()
            tag = self._wait_for_first_tag()
            if tag is None:
                store.add_error(
                    phase="tag_detection",
                    code="tag_timeout",
                    message=f"Žádný tag do {self.config.tag_timeout}s",
                )
                overall = OverallStatus.FAILED
            else:
                self._uid = tag.id_hex.upper()
                self._tag_type = tag.tag_type
                # Keep the working directory stable (UID-pending) until finalize.
                # Renaming mid-capture breaks open raw_serial.jsonl paths.
                store.update_summary(uid=self._uid)
                store.append_event("uid_locked", uid=self._uid, dir=str(store.root))
                self._fire_event("tag_detected", uid=self._uid)
                if self._uid_gate is not None and not self._uid_gate(self._uid):
                    self._duplicate = True
                    store.write_phase(
                        "uid_confirm",
                        {"reason": "duplicate_skipped", "uid": self._uid},
                        PhaseStatus.SKIPPED.value,
                    )
                    self._fire_event("duplicate_skipped", uid=self._uid)
                    overall = OverallStatus.PARTIAL
                else:
                    self._announce_detected()
                    self._run_capture_once()
                    self._capture_ran = True
                    usable = self._has_usable_data()
                    overall = compute_overall(
                        store.phase_statuses,
                        uid=self._uid,
                        usable_data=usable,
                    )
        except BaseException as exc:  # noqa: BLE001
            store.add_error(
                phase="probe",
                code="fatal",
                message=str(exc),
            )
            usable = self._has_usable_data()
            overall = compute_overall(
                store.phase_statuses,
                uid=self._uid,
                usable_data=usable,
            )
            if not usable and not self._uid:
                overall = OverallStatus.FAILED
        finally:
            # Close tracer → close serial → then rename pending dir.
            self._close_raw_trace()
            self._close_port()
            if self._uid:
                store.finalize_rename(self._uid)
            self._store = store
            store.update_summary(
                uid=self._uid,
                tag_type=self._format_tag_type(),
                overall_status=overall.value,
                output_dir=str(store.root),
            )
            store.finalize(overall.value)
            self._print_result(overall)

        return ProbeResult(
            overall=overall,
            uid=self._uid,
            output_dir=store.root,
            phase_statuses=dict(store.phase_statuses),
            errors=list(store.errors),
            port_closed=self._port_closed,
            duplicate=self._duplicate,
            aborted=self._aborted,
        )

    # ------------------------------------------------------------------ helpers

    def _stopping(self) -> bool:
        return bool(self._stop is not None and self._stop.is_set())

    def _fire_event(self, name: str, **payload: Any) -> None:
        if self._on_event is not None:
            self._on_event(name, payload)

    def _phase_begin(self, phase_key: str) -> None:
        """Notify consumers that a capture phase is starting (HWSniff LED progress)."""
        self._fire_event("phase_started", phase=phase_key)
        if self._on_phase is not None:
            self._on_phase(phase_key, "started")

    def _phase_end(self, phase_key: str, status: str) -> None:
        self._fire_event("phase_complete", phase=phase_key, status=status)
        if self._on_phase is not None:
            self._on_phase(phase_key, status)

    def _emit(self, line: str) -> None:
        if not self.config.quiet:
            if self._stdout is not None:
                print(line, file=self._stdout, flush=True)
            else:
                print(line, flush=True)
        if self._store is not None:
            self._store.log_console(line)

    def _attach_raw_trace(self, path: Path) -> None:
        assert self._client is not None
        store = self._store

        def on_trace_error(message: str, exc: BaseException) -> None:
            if store is None:
                return
            code = "raw_trace_error"
            store.add_error(
                phase="raw_trace",
                code=code,
                message=message,
                details={"path": str(path)},
            )

        try:
            self._tracer = RawSerialTracer(path, on_error=on_trace_error)
            transport = getattr(self._client, "transport", None)
            if transport is None or not hasattr(transport, "exchange"):
                raise AttributeError("client has no transport.exchange for raw trace")
            transport.exchange = self._tracer.wrap_exchange(transport.exchange)
        except Exception as exc:  # noqa: BLE001 — fail-soft: never abort capture
            self._tracer = None
            on_trace_error(f"raw tracer disabled: {exc}", exc)
            if store is not None:
                store.append_event("raw_trace_disabled", error=str(exc))
            return
        if store is not None:
            store._track(path)  # noqa: SLF001
            store.append_event("raw_trace_enabled", path=str(path))

    def _close_raw_trace(self) -> None:
        tracer = self._tracer
        self._tracer = None
        if tracer is None:
            return
        try:
            tracer.close()
        except Exception:  # noqa: BLE001
            pass
        if self._store is not None:
            self._store.append_event(
                "raw_trace_closed",
                path=str(tracer.path),
                io_errors=list(tracer.io_errors),
            )

    def _close_port(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            self._port_closed = True
            return
        try:
            client.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        self._port_closed = True
        if self._store is not None:
            self._store.append_event("port_closed", port=self.config.port)

    def _format_tag_type(self) -> str | None:
        if self._tag_type is None:
            return None
        base = f"0x{self._tag_type:02X}"
        if self._ntag_capable:
            return f"{base} / NTAG I2C Plus"
        return base

    def _has_usable_data(self) -> bool:
        if self._store is None:
            return False
        if self._uid:
            return True
        return any(
            s in (PhaseStatus.OK.value, PhaseStatus.PARTIAL.value)
            for s in self._store.phase_statuses.values()
        )

    def _attempts_payload(self, attempts: list[AttemptRecord]) -> list[dict[str, Any]]:
        return [
            {
                "attempt": a.attempt,
                "status": a.status,
                "latency_ms": a.latency_ms,
                "error": a.error,
            }
            for a in attempts
        ]

    def _phase_banner(self, title: str, detail: str, *, phase_key: str | None = None) -> None:
        self._phase_index += 1
        self._emit(f"[{self._phase_index}/{self._phase_total}] {title} {detail}")
        if phase_key and self._on_phase is not None:
            self._on_phase(phase_key, detail)

    def _reselect_same_uid(self) -> None:
        assert self._client is not None and self._uid is not None
        tag = self._search_tag()
        if tag is None:
            raise SerialCommunicationError("Tag lost during capture")
        if tag.id_hex.upper() != self._uid:
            if self._store is not None:
                self._store.add_error(
                    phase="uid_guard",
                    code="uid_changed",
                    message=(
                        f"Během capture se objevilo jiné UID: "
                        f"{self._uid} → {tag.id_hex.upper()}"
                    ),
                    details={
                        "original_uid": self._uid,
                        "seen_uid": tag.id_hex.upper(),
                    },
                )
            raise SerialCommunicationError(
                f"UID changed during capture: {self._uid} → {tag.id_hex.upper()}"
            )

    def _search_tag(self) -> TagRead | None:
        assert self._client is not None
        tag = self._client.search_tag()
        if tag is not None:
            return tag
        try:
            self._client.set_rf_off()
            self._sleep(0.05)
        except (ElatecError, SerialCommunicationError, OSError, AttributeError):
            pass
        return self._client.search_tag()

    def _guard_uid_if_present(self, tag: TagRead) -> None:
        if self._uid is None:
            return
        if tag.id_hex.upper() != self._uid:
            if self._store is not None:
                self._store.add_error(
                    phase="uid_guard",
                    code="uid_changed",
                    message=(
                        f"Detekováno jiné UID, původní ponecháno: "
                        f"{self._uid} (seen {tag.id_hex.upper()})"
                    ),
                    details={
                        "original_uid": self._uid,
                        "seen_uid": tag.id_hex.upper(),
                    },
                )
            raise SerialCommunicationError(
                f"UID changed: expected {self._uid}, got {tag.id_hex.upper()}"
            )

    # ------------------------------------------------------------------ phases

    def _run_reader_info(self) -> None:
        store = self._store
        assert store is not None and self._client is not None

        def op() -> dict[str, Any]:
            info: dict[str, Any] = {"port": self.config.port}
            try:
                version = self._client.get_version_string()
                info["version"] = version
            except (
                ElatecError,
                SerialCommunicationError,
                ProtocolError,
                OSError,
                AttributeError,
            ) as exc:
                info["version_error"] = str(exc)
            try:
                device_type = self._client.get_device_type()
                info["device_type"] = device_type
            except (
                ElatecError,
                SerialCommunicationError,
                ProtocolError,
                OSError,
                AttributeError,
            ) as exc:
                info["device_type_error"] = str(exc)
            try:
                lf, hf = self._client.get_supported_tag_types()
                info["lf_supported_mask"] = lf
                info["hf_supported_mask"] = hf
            except (
                ElatecError,
                SerialCommunicationError,
                ProtocolError,
                OSError,
                AttributeError,
            ) as exc:
                info["tag_types_error"] = str(exc)
            # Soft OK when reader opened successfully even if info methods are stubs.
            if "version" not in info and "device_type" not in info:
                info["version"] = "unavailable"
                info["soft"] = True
            return info

        result = run_with_retry(
            op,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
        )
        attempts = self._attempts_payload(result.attempts)
        data = result.value or {}
        data["attempts"] = attempts
        status = result.status
        if result.status == PhaseStatus.OK and (
            "version_error" in data or "device_type_error" in data
        ):
            status = PhaseStatus.PARTIAL
        store.write_phase("reader_info", data, status.value)
        store.update_summary(reader=data)
        latency = attempts[-1]["latency_ms"] if attempts else 0
        label = status.value.upper()
        self._phase_banner("Reader info", f"........ {label} ({latency:.0f} ms)")

    def _wait_for_first_tag(self) -> TagRead | None:
        store = self._store
        assert store is not None and self._client is not None
        deadline = time.monotonic() + float(self.config.tag_timeout)
        polls = 0
        while time.monotonic() < deadline:
            if self._stopping():
                self._aborted = True
                store.write_phase(
                    "tag_detection",
                    {"polls": polls, "aborted": True},
                    PhaseStatus.TIMEOUT.value,
                )
                return None
            polls += 1
            try:
                tag = self._search_tag()
            except (ElatecError, SerialCommunicationError, ProtocolError, OSError) as exc:
                store.append_event("search_error", error=str(exc))
                self._sleep(self.config.poll_interval_seconds)
                continue
            if tag is not None:
                data = {
                    "uid": tag.id_hex.upper(),
                    "tag_type": tag.tag_type,
                    "id_bit_count": tag.id_bit_count,
                    "polls": polls,
                    "attempts": [
                        {
                            "attempt": 1,
                            "status": PhaseStatus.OK.value,
                            "latency_ms": 0,
                        }
                    ],
                }
                store.write_phase("tag_detection", data, PhaseStatus.OK.value)
                self._phase_banner("Wait for tag", f"...... UID {tag.id_hex.upper()}")
                return tag
            self._sleep(self.config.poll_interval_seconds)

        store.write_phase(
            "tag_detection",
            {"polls": polls, "timeout_s": self.config.tag_timeout},
            PhaseStatus.TIMEOUT.value,
        )
        self._phase_banner("Wait for tag", "...... TIMEOUT")
        return None

    def _announce_detected(self) -> None:
        assert self._uid is not None
        self._emit(f"TAG DETECTED: {self._uid}")
        self._emit("TAG DETECTED — NEHÝBEJTE SE ŠTÍTKEM")
        self._emit("NEHÝBEJTE TAGEM ANI ČTEČKOU")
        self._emit("Spouštím jednorázový read-only capture...")
        if self._store is not None:
            self._store.append_event("tag_locked", uid=self._uid)

    def _run_capture_once(self) -> None:
        """Exactly one capture for the locked UID. No wait-for-removal."""
        if self._capture_ran:
            raise RuntimeError("Capture already ran")
        steps: list[tuple[str, Callable[[], None]]] = [
            ("uid_confirm", self._confirm_uid),
            ("identification", self._run_identification),
        ]
        if self.config.skip_eeprom:
            steps.append(
                ("eeprom", lambda: self._skip_phase("eeprom", "skipped by --skip-eeprom"))
            )
        else:
            steps.append(("eeprom", self._run_eeprom))
        if self.config.skip_application:
            steps.append(
                (
                    "application",
                    lambda: self._skip_phase(
                        "application", "skipped by --skip-application"
                    ),
                )
            )
        else:
            steps.append(("application", self._run_application))
        if self.config.skip_session:
            steps.append(
                (
                    "session",
                    lambda: self._skip_phase("session", "skipped by --skip-session"),
                )
            )
        else:
            steps.append(("session", self._run_session))
        steps.append(("verification", self._run_verification))

        for phase_key, fn in steps:
            if self._stopping():
                self._aborted = True
                self._fire_event("capture_aborted", phase=phase_key)
                return
            self._phase_begin(phase_key)
            fn()

    def _skip_phase(self, name: str, reason: str) -> None:
        assert self._store is not None
        self._store.write_phase(
            name, {"reason": reason}, PhaseStatus.SKIPPED.value
        )
        titles = {
            "eeprom": "EEPROM ............",
            "application": "Application .......",
            "session": "Session ...........",
        }
        self._phase_banner(titles.get(name, name), "SKIPPED")
        self._phase_end(name, PhaseStatus.SKIPPED.value)

    def _confirm_uid(self) -> None:
        store = self._store
        assert store is not None and self._uid is not None
        needed = max(1, int(self.config.confirm_reads))
        successes: list[str] = []
        attempts_out: list[dict[str, Any]] = []

        for i in range(1, needed + 1):
            t0 = time.monotonic()
            try:
                tag = self._search_tag()
                latency = (time.monotonic() - t0) * 1000.0
                if tag is None:
                    attempts_out.append(
                        {
                            "attempt": i,
                            "status": PhaseStatus.TIMEOUT.value,
                            "latency_ms": round(latency, 2),
                            "error": "no tag",
                        }
                    )
                    self._sleep(self.config.retry_delay_ms / 1000.0)
                    continue
                self._guard_uid_if_present(tag)
                successes.append(tag.id_hex.upper())
                attempts_out.append(
                    {
                        "attempt": i,
                        "status": PhaseStatus.OK.value,
                        "latency_ms": round(latency, 2),
                        "uid": tag.id_hex.upper(),
                    }
                )
            except BaseException as exc:  # noqa: BLE001 — classify per attempt
                latency = (time.monotonic() - t0) * 1000.0
                status_i = classify_exception(exc)
                attempts_out.append(
                    {
                        "attempt": i,
                        "status": status_i.value,
                        "latency_ms": round(latency, 2),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self._sleep(self.config.retry_delay_ms / 1000.0)

        ok_count = len(successes)
        status = aggregate_attempt_statuses(
            [a["status"] for a in attempts_out],
            success_count=ok_count,
            required_successes=needed,
        )

        store.write_phase(
            "uid_confirm",
            {
                "expected_uid": self._uid,
                "confirmed": successes,
                "required": needed,
                "attempts": attempts_out,
            },
            status.value,
        )
        self._emit(
            f"    UID confirm ........ {status.value.upper()} ({ok_count}/{needed})"
        )
        self._phase_end("uid_confirm", status.value)

    def _run_identification(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        ntag = NtagI2CPlus(self._client)

        def op() -> dict[str, Any]:
            self._reselect_same_uid()
            version = ntag.get_version()
            return {
                "raw_hex": version.raw.hex(" ").upper(),
                "vendor_id": version.vendor_id,
                "product_type": version.product_type,
                "product_subtype": version.product_subtype,
                "major_version": version.major_version,
                "minor_version": version.minor_version,
                "storage_size": version.storage_size,
                "protocol_type": version.protocol_type,
                "is_ntag_i2c_plus_1k": version.is_ntag_i2c_plus_1k,
            }

        result = run_with_retry(
            op,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
            reselect=self._reselect_same_uid,
        )
        attempts = self._attempts_payload(result.attempts)
        if result.status == PhaseStatus.OK and result.value:
            self._ntag_capable = bool(
                result.value.get("is_ntag_i2c_plus_1k")
                or result.value.get("vendor_id") == 0x04
            )
            data = {**result.value, "attempts": attempts}
            store.write_phase("identification", data, PhaseStatus.OK.value)
            store.update_summary(tag_type=self._format_tag_type(), identification=data)
            latency = attempts[-1]["latency_ms"] if attempts else 0
            self._phase_banner("Identification", f".... OK ({latency:.0f} ms)")
            self._phase_end("identification", PhaseStatus.OK.value)
            return

        # Non-NTAG or GET_VERSION unsupported — still continue other phases carefully.
        err = result.error or "GET_VERSION failed"
        # Treat clear NAK/invalid as unsupported for non-NTAG.
        status = (
            PhaseStatus.UNSUPPORTED
            if "NAK" in err or "invalid" in err.lower()
            else result.status
        )
        store.write_phase(
            "identification",
            {"error": err, "attempts": attempts},
            status.value,
        )
        store.add_error(
            phase="identification",
            code=status.value,
            message=err,
        )
        self._phase_banner("Identification", f".... {status.value.upper()}")
        self._phase_end("identification", status.value)

    def _run_eeprom(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        if not self._ntag_capable:
            store.write_phase(
                "eeprom",
                {"reason": "GET_VERSION nenaznačuje NTAG I2C Plus"},
                PhaseStatus.UNSUPPORTED.value,
            )
            self._phase_banner("EEPROM ............", "UNSUPPORTED")
            self._phase_end("eeprom", PhaseStatus.UNSUPPORTED.value)
            return

        ntag = NtagI2CPlus(self._client)
        pages: dict[str, str] = {}
        chunk_attempts: list[dict[str, Any]] = []
        ok_chunks = 0
        total_chunks = 0
        page = FULL_DUMP_START_PAGE
        planned_chunks = (
            (FULL_DUMP_END_PAGE - FULL_DUMP_START_PAGE) // FULL_DUMP_CHUNK_PAGES
        ) + 1
        while page <= FULL_DUMP_END_PAGE:
            if self._stopping():
                self._aborted = True
                break
            end = min(page + FULL_DUMP_CHUNK_PAGES - 1, FULL_DUMP_END_PAGE)
            total_chunks += 1
            self._fire_event(
                "phase_progress",
                phase="eeprom",
                current=total_chunks,
                total=planned_chunks,
            )

            def chunk_op(start: int = page, stop: int = end) -> bytes:
                self._reselect_same_uid()
                return ntag.read_eeprom_range(start, stop)

            result = run_with_retry(
                chunk_op,
                retry_count=self.config.retry_count,
                retry_delay_ms=self.config.retry_delay_ms,
                sleep=self._sleep,
                reselect=self._reselect_same_uid,
            )
            chunk_attempts.append(
                {
                    "start_page": page,
                    "end_page": end,
                    "status": result.status.value,
                    "attempts": self._attempts_payload(result.attempts),
                    "error": result.error,
                }
            )
            if result.status == PhaseStatus.OK and result.value is not None:
                ok_chunks += 1
                data = result.value
                for i in range(end - page + 1):
                    off = i * 4
                    pages[f"0x{page + i:02X}"] = data[off : off + 4].hex(" ").upper()
                # Persist incrementally after each successful chunk.
                store.write_phase(
                    "eeprom",
                    {
                        "start_page": FULL_DUMP_START_PAGE,
                        "end_page": FULL_DUMP_END_PAGE,
                        "pages_ok": len(pages),
                        "chunks_ok": ok_chunks,
                        "chunks_total": total_chunks,
                        "pages": pages,
                        "chunk_attempts": chunk_attempts,
                    },
                    PhaseStatus.PARTIAL.value
                    if ok_chunks < total_chunks
                    else PhaseStatus.OK.value,
                )
            else:
                store.add_error(
                    phase="eeprom",
                    code=result.status.value,
                    message=result.error or f"chunk 0x{page:02X}-0x{end:02X}",
                )
                store.write_phase(
                    "eeprom",
                    {
                        "start_page": FULL_DUMP_START_PAGE,
                        "end_page": FULL_DUMP_END_PAGE,
                        "pages_ok": len(pages),
                        "chunks_ok": ok_chunks,
                        "chunks_total": total_chunks,
                        "pages": pages,
                        "chunk_attempts": chunk_attempts,
                    },
                    PhaseStatus.PARTIAL.value if pages else result.status.value,
                )
            page = end + 1

        if ok_chunks == total_chunks and pages:
            status = PhaseStatus.OK
        elif pages:
            status = PhaseStatus.PARTIAL
        else:
            status = PhaseStatus.TIMEOUT
        store.write_phase(
            "eeprom",
            {
                "start_page": FULL_DUMP_START_PAGE,
                "end_page": FULL_DUMP_END_PAGE,
                "pages_ok": len(pages),
                "chunks_ok": ok_chunks,
                "chunks_total": total_chunks,
                "pages": pages,
                "chunk_attempts": chunk_attempts,
            },
            status.value,
        )
        self._phase_banner(
            "EEPROM ............",
            f"{status.value.upper()}, {ok_chunks}/{total_chunks} chunks",
        )
        self._phase_end("eeprom", status.value)

    def _run_application(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        if not self._ntag_capable:
            # Still try page 00 as a safe Type-2 READ if identification failed soft.
            self._try_page00_fallback()
            return

        ntag = NtagI2CPlus(self._client)

        def op() -> dict[str, Any]:
            self._reselect_same_uid()
            data = ntag.read_eeprom_range(
                EEPROM_WATCH_START_PAGE, EEPROM_WATCH_END_PAGE
            )
            pages = {
                f"0x{EEPROM_WATCH_START_PAGE + i:02X}": data[i * 4 : (i + 1) * 4].hex(
                    " "
                ).upper()
                for i in range(EEPROM_WATCH_END_PAGE - EEPROM_WATCH_START_PAGE + 1)
            }
            page00 = ntag.read_block(0x00)
            return {
                "start_page": EEPROM_WATCH_START_PAGE,
                "end_page": EEPROM_WATCH_END_PAGE,
                "raw_hex": data.hex(" ").upper(),
                "pages": pages,
                "page_00_hex": page00.hex(" ").upper(),
            }

        result = run_with_retry(
            op,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
            reselect=self._reselect_same_uid,
        )
        attempts = self._attempts_payload(result.attempts)
        if result.status == PhaseStatus.OK and result.value:
            data = {**result.value, "attempts": attempts}
            store.write_phase("application", data, PhaseStatus.OK.value)
            latency = attempts[-1]["latency_ms"] if attempts else 0
            self._phase_banner("Application .......", f"OK ({latency:.0f} ms)")
            self._phase_end("application", PhaseStatus.OK.value)
            return

        store.write_phase(
            "application",
            {"error": result.error, "attempts": attempts},
            result.status.value,
        )
        store.add_error(
            phase="application",
            code=result.status.value,
            message=result.error or "application read failed",
        )
        self._phase_banner(
            "Application .......",
            f"{result.status.value.upper()} after {len(attempts)} retries",
        )
        self._phase_end("application", result.status.value)

    def _try_page00_fallback(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        ntag = NtagI2CPlus(self._client)

        def op() -> dict[str, Any]:
            self._reselect_same_uid()
            page00 = ntag.read_block(0x00)
            return {"page_00_hex": page00.hex(" ").upper()}

        result = run_with_retry(
            op,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
            reselect=self._reselect_same_uid,
        )
        attempts = self._attempts_payload(result.attempts)
        if result.status == PhaseStatus.OK and result.value:
            store.write_phase(
                "application",
                {**result.value, "attempts": attempts, "mode": "page00_fallback"},
                PhaseStatus.PARTIAL.value,
            )
            self._phase_banner("Application .......", "PARTIAL (page 00 only)")
            self._phase_end("application", PhaseStatus.PARTIAL.value)
            return
        store.write_phase(
            "application",
            {
                "reason": "tag technology not NTAG I2C Plus",
                "error": result.error,
                "attempts": attempts,
            },
            PhaseStatus.UNSUPPORTED.value,
        )
        self._phase_banner("Application .......", "UNSUPPORTED")
        self._phase_end("application", PhaseStatus.UNSUPPORTED.value)

    def _run_session(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        if not self._ntag_capable:
            store.write_phase(
                "session",
                {"reason": "GET_VERSION nenaznačuje NTAG I2C Plus"},
                PhaseStatus.UNSUPPORTED.value,
            )
            self._phase_banner("Session ...........", "UNSUPPORTED")
            self._phase_end("session", PhaseStatus.UNSUPPORTED.value)
            return

        ntag = NtagI2CPlus(self._client)
        samples: list[dict[str, Any]] = []
        deadline = time.monotonic() + float(self.config.session_seconds)
        interval = max(0.0, float(self.config.session_interval_ms) / 1000.0)
        errors = 0

        while time.monotonic() < deadline:
            if self._stopping():
                self._aborted = True
                break
            t0 = time.monotonic()
            try:
                self._reselect_same_uid()
                raw = ntag.read_session_registers()
                registers = {
                    SESSION_REGISTER_NAMES[i]: raw[i]
                    for i in range(min(len(SESSION_REGISTER_NAMES), len(raw)))
                }
                samples.append(
                    {
                        "t_mono": t0,
                        "raw_hex": raw.hex(" ").upper(),
                        "registers": registers,
                    }
                )
                # Persist incrementally.
                store.write_phase(
                    "session",
                    {
                        "samples": samples,
                        "sample_count": len(samples),
                        "errors": errors,
                        "duration_s": self.config.session_seconds,
                    },
                    PhaseStatus.OK.value if samples else PhaseStatus.PARTIAL.value,
                )
            except (
                ElatecError,
                SerialCommunicationError,
                ProtocolError,
                OSError,
            ) as exc:
                errors += 1
                store.add_error(
                    phase="session",
                    code="sample_error",
                    message=str(exc),
                )
            self._sleep(interval)

        if samples and errors == 0:
            status = PhaseStatus.OK
        elif samples:
            status = PhaseStatus.PARTIAL
        else:
            status = PhaseStatus.TIMEOUT
        store.write_phase(
            "session",
            {
                "samples": samples,
                "sample_count": len(samples),
                "errors": errors,
                "duration_s": self.config.session_seconds,
            },
            status.value,
        )
        self._phase_banner(
            "Session ...........",
            f"{status.value.upper()}, {len(samples)} samples",
        )
        self._phase_end("session", status.value)

    def _run_verification(self) -> None:
        store = self._store
        assert store is not None and self._client is not None
        checks: dict[str, Any] = {}

        def uid_check() -> str:
            self._reselect_same_uid()
            tag = self._search_tag()
            if tag is None:
                raise SerialCommunicationError("Tag missing during verification")
            self._guard_uid_if_present(tag)
            return tag.id_hex.upper()

        uid_result = run_with_retry(
            uid_check,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
        )
        checks["uid"] = {
            "status": uid_result.status.value,
            "value": uid_result.value,
            "attempts": self._attempts_payload(uid_result.attempts),
            "error": uid_result.error,
        }

        if self._ntag_capable:
            ntag = NtagI2CPlus(self._client)

            def ver_op() -> dict[str, str]:
                self._reselect_same_uid()
                version = ntag.get_version()
                app = ntag.read_eeprom_range(
                    EEPROM_WATCH_START_PAGE, EEPROM_WATCH_END_PAGE
                )
                return {
                    "version_hex": version.raw.hex(" ").upper(),
                    "application_hex": app.hex(" ").upper(),
                }

            ver_result = run_with_retry(
                ver_op,
                retry_count=self.config.retry_count,
                retry_delay_ms=self.config.retry_delay_ms,
                sleep=self._sleep,
                reselect=self._reselect_same_uid,
            )
            checks["ntag"] = {
                "status": ver_result.status.value,
                "value": ver_result.value,
                "attempts": self._attempts_payload(ver_result.attempts),
                "error": ver_result.error,
            }

        statuses = [v["status"] for v in checks.values()]
        ok_n = sum(1 for s in statuses if s == PhaseStatus.OK.value)
        status = aggregate_attempt_statuses(
            statuses,
            success_count=ok_n,
            required_successes=len(statuses) if statuses else 1,
        )

        store.write_phase("verification", {"checks": checks}, status.value)
        self._phase_banner("Verification ......", status.value.upper())
        self._phase_end("verification", status.value)

    def _print_result(self, overall: OverallStatus) -> None:
        store = self._store
        assert store is not None
        statuses = store.phase_statuses
        ok = sum(1 for s in statuses.values() if s == PhaseStatus.OK.value)
        failed = sum(
            1
            for s in statuses.values()
            if s
            in {
                PhaseStatus.TIMEOUT.value,
                PhaseStatus.SERIAL_TIMEOUT.value,
                PhaseStatus.READER_ERROR.value,
                PhaseStatus.PROTOCOL_ERROR.value,
                PhaseStatus.PERSISTENCE_ERROR.value,
                PhaseStatus.RAW_TRACE_ERROR.value,
                PhaseStatus.EXCEPTION.value,
            }
        )
        unsupported = sum(
            1 for s in statuses.values() if s == PhaseStatus.UNSUPPORTED.value
        )
        self._emit("")
        self._emit(f"RESULT: {overall.value}")
        self._emit(f"UID: {self._uid or '-'}")
        self._emit(f"Successful phases: {ok}")
        self._emit(f"Failed phases: {failed}")
        self._emit(f"Unsupported phases: {unsupported}")
        self._emit(f"Output: {store.root}")
