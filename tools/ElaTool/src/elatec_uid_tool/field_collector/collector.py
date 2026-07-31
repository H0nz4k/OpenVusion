from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .. import __version__
from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient
from .models import (
    CapturePhase,
    CaptureProgress,
    CollectorConfig,
    FieldCaptureResult,
    FinishStatus,
)
from .storage import (
    append_index,
    create_capture_directory,
    index_contains_uid,
    sha256_bytes,
    verify_artifacts,
    write_json,
)

ProgressCallback = Callable[[CaptureProgress], None]
EventCallback = Callable[[str, dict[str, Any]], None]


class FieldCollector:
    """Read-only field capture orchestrator (no NFC writes)."""

    FORBIDDEN_METHODS = (
        "write",
        "fast_write",
        "compatibility_write",
        "pwd_auth",
        "read_sram",
    )

    def __init__(
        self,
        config: CollectorConfig,
        *,
        client_factory: Callable[[str, float], Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or (
            lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)
        )
        self._sleep = sleep or time.sleep
        self._clock = clock or (lambda: datetime.now().astimezone().isoformat())
        self._stop = threading.Event()
        self._busy = threading.Event()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def clear_stop(self) -> None:
        self._stop.clear()

    def capture_one(
        self,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> FieldCaptureResult:
        self._busy.set()
        errors: list[str] = []
        uid: str | None = None
        get_version: str | None = None
        app_hex: str | None = None
        directory: Path | None = None
        hashes: dict[str, str] = {}

        def progress(phase: CapturePhase, **kwargs: Any) -> None:
            if on_progress:
                on_progress(CaptureProgress(phase=phase, **kwargs))

        def emit(name: str, **payload: Any) -> None:
            if on_event:
                on_event(name, payload)

        try:
            emit("capture_started", port=port)
            with self._client_factory(port, self.config.handshake_timeout_seconds) as client:
                progress(CapturePhase.IDENTIFICATION, message="SearchTag")
                tag = None
                deadline = time.monotonic() + 30.0
                while tag is None:
                    if self._stop.is_set():
                        return FieldCaptureResult(
                            uid=None,
                            get_version=None,
                            directory=None,
                            finish_status=FinishStatus.ABORTED,
                            errors=["aborted before tag"],
                        )
                    tag = client.search_tag()
                    if tag is None:
                        self._sleep(self.config.poll_interval_seconds)
                        if time.monotonic() > deadline:
                            raise SerialCommunicationError("Tag timeout")
                uid = tag.id_hex
                emit("tag_detected", uid=uid)

                data_root = Path(self.config.resolved_data_root())
                if (
                    not self.config.allow_duplicate
                    and uid
                    and index_contains_uid(data_root, uid)
                ):
                    emit("duplicate_skipped", uid=uid)
                    return FieldCaptureResult(
                        uid=uid,
                        get_version=None,
                        directory=None,
                        finish_status=FinishStatus.DUPLICATE_SKIPPED,
                        duplicate=True,
                    )

                ntag = NtagI2CPlus(client)
                progress(CapturePhase.IDENTIFICATION, message="GET_VERSION")
                version = ntag.get_version()
                get_version = version.raw.hex(" ").upper()

                app_blocks: list[bytes] = []
                total = max(1, self.config.application_samples)
                for index in range(1, total + 1):
                    progress(
                        CapturePhase.APPLICATION_BLOCK,
                        sample_index=index,
                        sample_total=total,
                        message=f"APPLICATION {index}/{total}",
                    )
                    block = ntag.read_eeprom_range(
                        EEPROM_WATCH_START_PAGE,
                        EEPROM_WATCH_END_PAGE,
                    )
                    app_blocks.append(block)
                    if index < total:
                        self._sleep(0.05)

                if len({b.hex() for b in app_blocks}) != 1:
                    errors.append("application block samples differ")
                app = app_blocks[0]
                app_hex = app.hex(" ").upper()

                session_bytes: bytes | None = None
                if self.config.include_session and self.config.session_duration_seconds > 0:
                    progress(CapturePhase.SESSION, message="SESSION")
                    samples: list[bytes] = []
                    end = time.monotonic() + self.config.session_duration_seconds
                    while time.monotonic() < end:
                        samples.append(ntag.read_session_registers())
                        self._sleep(self.config.session_interval_ms / 1000.0)
                    session_bytes = samples[0] if samples else None

                full_dump: bytes | None = None
                if self.config.include_full_dump and self.config.full_dump_samples > 0:
                    progress(CapturePhase.EEPROM, message="EEPROM")
                    # Limited safe user-memory window via existing helper range.
                    full_dump = ntag.read_eeprom_range(0x00, 0x3F)

                progress(CapturePhase.SAVING, message="SAVING")
                directory = create_capture_directory(
                    Path(self.config.capture_root), uid
                )
                (directory / "application_block.bin").write_bytes(app)
                write_json(
                    directory / "application_block.json",
                    {
                        "uid": uid,
                        "get_version": get_version,
                        "raw_hex": app_hex,
                        "pages": {
                            f"0x{EEPROM_WATCH_START_PAGE + i:02X}": app[
                                i * 4 : (i + 1) * 4
                            ].hex(" ").upper()
                            for i in range(8)
                        },
                    },
                )
                required = ["application_block.bin", "application_block.json"]
                if session_bytes is not None:
                    (directory / "session.bin").write_bytes(session_bytes)
                    required.append("session.bin")
                if full_dump is not None:
                    (directory / "dump.bin").write_bytes(full_dump)
                    required.append("dump.bin")

                metadata = {
                    "schema_version": 1,
                    "tool": "field_collector",
                    "tool_version": __version__,
                    "read_only": True,
                    "uid": uid,
                    "get_version": get_version,
                    "label": self.config.label,
                    "state": self.config.state,
                    "notes": self.config.notes,
                    "started_at": self._clock(),
                    "finished_at": self._clock(),
                    "application_samples": total,
                    "application_stable": len({b.hex() for b in app_blocks}) == 1,
                    "port": port,
                }
                write_json(directory / "metadata.json", metadata)
                required.append("metadata.json")

                progress(CapturePhase.VERIFYING, message="VERIFYING")
                hashes = verify_artifacts(directory, required)
                hashes["application_block_bytes"] = sha256_bytes(app)

                status = (
                    FinishStatus.COMPLETED_WITH_ERRORS
                    if errors
                    else FinishStatus.COMPLETED_SUCCESSFULLY
                )
                metadata["finish_status"] = status.value
                metadata["sha256"] = hashes
                write_json(directory / "metadata.json", metadata)
                (directory / "report.txt").write_text(
                    f"UID: {uid}\nGET_VERSION: {get_version}\n"
                    f"Status: {status.value}\n"
                    f"Application: {app_hex}\n",
                    encoding="utf-8",
                )

                append_index(
                    data_root,
                    {
                        "timestamp": metadata["finished_at"],
                        "uid": uid,
                        "get_version": get_version,
                        "finish_status": status.value,
                        "directory": str(directory),
                        "duplicate": False,
                        "application_sha256": hashes.get(
                            "application_block.bin", ""
                        ),
                    },
                )
                emit("capture_finished", uid=uid, status=status.value)
                return FieldCaptureResult(
                    uid=uid,
                    get_version=get_version,
                    directory=str(directory),
                    finish_status=status,
                    application_block_hex=app_hex,
                    sha256=hashes,
                    errors=errors,
                    metadata=metadata,
                )
        except (ElatecError, SerialCommunicationError, OSError, ValueError) as exc:
            errors.append(str(exc))
            emit("capture_error", error=str(exc), uid=uid)
            if directory is not None:
                write_json(
                    directory / "metadata.json",
                    {
                        "uid": uid,
                        "finish_status": FinishStatus.PARTIAL.value,
                        "errors": errors,
                        "read_only": True,
                    },
                )
            return FieldCaptureResult(
                uid=uid,
                get_version=get_version,
                directory=str(directory) if directory else None,
                finish_status=FinishStatus.PARTIAL,
                application_block_hex=app_hex,
                sha256=hashes,
                errors=errors,
            )
        finally:
            self._busy.clear()

    def run_continuous(
        self,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
        on_result: Callable[[FieldCaptureResult], None] | None = None,
    ) -> None:
        """Poll for tags until request_stop(). Finishes in-flight capture."""
        self.clear_stop()
        emit = on_event or (lambda n, p: None)
        emit("loop_started", port=port)
        while not self._stop.is_set():
            try:
                with self._client_factory(
                    port, self.config.handshake_timeout_seconds
                ) as client:
                    while not self._stop.is_set():
                        tag = client.search_tag()
                        if tag is None:
                            self._sleep(self.config.poll_interval_seconds)
                            continue
                        # Capture using a fresh client session inside capture_one.
                        break
                if self._stop.is_set():
                    break
                result = self.capture_one(
                    port, on_progress=on_progress, on_event=on_event
                )
                if on_result:
                    on_result(result)
                if (
                    self.config.wait_for_removal
                    and result.uid
                    and result.finish_status
                    != FinishStatus.ABORTED
                ):
                    self._wait_for_removal(port)
            except (ElatecError, SerialCommunicationError, OSError) as exc:
                emit("loop_error", error=str(exc))
                self._sleep(1.0)
        emit("loop_stopped", port=port)

    def _wait_for_removal(self, port: str) -> None:
        try:
            with self._client_factory(
                port, self.config.handshake_timeout_seconds
            ) as client:
                while not self._stop.is_set():
                    if client.search_tag() is None:
                        return
                    self._sleep(0.2)
        except (ElatecError, SerialCommunicationError, OSError):
            return
