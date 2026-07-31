from __future__ import annotations

import tarfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .. import __version__
from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    SESSION_REGISTER_NAMES,
    NtagI2CPlus,
)
from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient, TagRead
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
    pack_capture_export,
    resolve_export_tar_path,
    sha256_bytes,
    verify_artifacts,
    write_json,
)

ProgressCallback = Callable[[CaptureProgress], None]
EventCallback = Callable[[str, dict[str, Any]], None]

# Full user EEPROM window used by ElaTool application capture (NTAG I²C Plus 1K).
FULL_DUMP_START_PAGE = 0x00
FULL_DUMP_END_PAGE = 0xE1
FULL_DUMP_CHUNK_PAGES = 16


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
        """One-shot capture (opens its own serial session)."""
        self._busy.set()
        try:

            def emit(name: str, **payload: Any) -> None:
                if on_event:
                    on_event(name, payload)

            emit("capture_started", port=port)
            with self._client_factory(
                port, self.config.handshake_timeout_seconds
            ) as client:
                tag = self._wait_for_tag(client, on_event=on_event)
                if tag is None:
                    return FieldCaptureResult(
                        uid=None,
                        get_version=None,
                        directory=None,
                        finish_status=FinishStatus.ABORTED,
                        errors=["aborted before tag"],
                    )
                return self._capture_selected(
                    client,
                    tag,
                    port,
                    on_progress=on_progress,
                    on_event=on_event,
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
        """One long-lived reader session: wait → full capture → removal → repeat."""
        self.clear_stop()

        def emit(name: str, **payload: Any) -> None:
            if on_event:
                on_event(name, payload)

        emit("loop_started", port=port)
        while not self._stop.is_set():
            try:
                with self._client_factory(
                    port, self.config.handshake_timeout_seconds
                ) as client:
                    while not self._stop.is_set():
                        result: FieldCaptureResult | None = None
                        self._busy.set()
                        try:
                            emit("capture_started", port=port)
                            tag = self._wait_for_tag(client, on_event=on_event)
                            if tag is None:
                                return
                            result = self._capture_selected(
                                client,
                                tag,
                                port,
                                on_progress=on_progress,
                                on_event=on_event,
                            )
                        finally:
                            self._busy.clear()

                        if result is None:
                            break
                        if on_result:
                            on_result(result)

                        need_removal = (
                            self.config.wait_for_removal
                            and result.uid
                            and result.finish_status != FinishStatus.ABORTED
                        ) or result.finish_status == FinishStatus.DUPLICATE_SKIPPED
                        if need_removal:
                            emit("waiting_for_removal", uid=result.uid)
                            try:
                                self._wait_for_removal_client(client)
                            except (
                                ElatecError,
                                SerialCommunicationError,
                                OSError,
                            ) as exc:
                                emit("loop_error", error=str(exc))
                            finally:
                                # Always unblock UI — even after serial errors —
                                # so the next present can start a new capture.
                                if not self._stop.is_set():
                                    emit("tag_removed", uid=result.uid)
                            if result.finish_status == FinishStatus.DUPLICATE_SKIPPED:
                                self._sleep(self.config.poll_interval_seconds)
            except (ElatecError, SerialCommunicationError, OSError) as exc:
                emit("loop_error", error=str(exc))
                # Unstick UI that may still show "Oddalte štítek".
                emit("tag_removed", uid=None)
                self._sleep(1.0)
        emit("loop_stopped", port=port)

    def _field_wake(self, client: Any) -> None:
        """Drop RF so a resting/HALTed tag will answer the next SearchTag."""
        try:
            client.set_rf_off()
        except (ElatecError, SerialCommunicationError, OSError, AttributeError):
            return
        self._sleep(0.05)

    def _search_tag(self, client: Any) -> TagRead | None:
        """SearchTag with RF wake — finds tags already sitting on the antenna."""
        tag = client.search_tag()
        if tag is not None:
            return tag
        self._field_wake(client)
        return client.search_tag()

    def _wait_for_tag(
        self,
        client: Any,
        *,
        on_event: EventCallback | None = None,
        timeout_seconds: float = 30.0,
    ) -> TagRead | None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self._stop.is_set():
                return None
            tag = self._search_tag(client)
            if tag is not None:
                if on_event:
                    on_event("tag_detected", {"uid": tag.id_hex})
                return tag
            self._sleep(self.config.poll_interval_seconds)
            if time.monotonic() > deadline:
                raise SerialCommunicationError("Tag timeout")

    def _wait_for_removal_client(self, client: Any) -> None:
        """Return when the tag is gone. Require two consecutive misses."""
        consecutive_misses = 0
        while not self._stop.is_set():
            # Wake-on-miss: HALTed-but-present tags must not look like "removed".
            tag = self._search_tag(client)
            if tag is None:
                consecutive_misses += 1
                if consecutive_misses >= 2:
                    return
            else:
                consecutive_misses = 0
            self._sleep(0.2)

    def _wait_for_removal(self, port: str) -> None:
        try:
            with self._client_factory(
                port, self.config.handshake_timeout_seconds
            ) as client:
                self._wait_for_removal_client(client)
        except (ElatecError, SerialCommunicationError, OSError):
            return

    def _ensure_selected(self, client: Any, expected_uid: str | None) -> TagRead:
        tag = self._search_tag(client)
        if tag is None:
            raise SerialCommunicationError("Tag lost during capture")
        if expected_uid and tag.id_hex.upper() != expected_uid.upper():
            raise SerialCommunicationError(
                f"UID changed during capture: {expected_uid} → {tag.id_hex}"
            )
        return tag

    def _read_full_dump(self, client: Any, ntag: NtagI2CPlus, uid: str) -> bytes:
        chunks: list[bytes] = []
        page = FULL_DUMP_START_PAGE
        while page <= FULL_DUMP_END_PAGE:
            end = min(page + FULL_DUMP_CHUNK_PAGES - 1, FULL_DUMP_END_PAGE)
            try:
                chunks.append(ntag.read_eeprom_range(page, end))
            except (ElatecError, SerialCommunicationError, ValueError):
                # Long dumps often need a reselect mid-way on TWN4.
                self._ensure_selected(client, uid)
                chunks.append(ntag.read_eeprom_range(page, end))
            page = end + 1
        return b"".join(chunks)

    def _capture_selected(
        self,
        client: Any,
        tag: TagRead,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> FieldCaptureResult:
        errors: list[str] = []
        uid: str | None = tag.id_hex
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
            progress(CapturePhase.IDENTIFICATION, message="SearchTag")
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
            # Reselect before RF reads — tag may already have been in the field.
            self._ensure_selected(client, uid)

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
                try:
                    block = ntag.read_eeprom_range(
                        EEPROM_WATCH_START_PAGE,
                        EEPROM_WATCH_END_PAGE,
                    )
                except (ElatecError, SerialCommunicationError, ValueError):
                    self._ensure_selected(client, uid)
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
            session_samples: list[bytes] = []
            if self.config.include_session and self.config.session_duration_seconds > 0:
                progress(CapturePhase.SESSION, message="SESSION")
                try:
                    self._ensure_selected(client, uid)
                    end = time.monotonic() + self.config.session_duration_seconds
                    while time.monotonic() < end:
                        try:
                            session_samples.append(ntag.read_session_registers())
                        except (ElatecError, SerialCommunicationError, ValueError):
                            self._ensure_selected(client, uid)
                            session_samples.append(ntag.read_session_registers())
                        self._sleep(self.config.session_interval_ms / 1000.0)
                    session_bytes = session_samples[0] if session_samples else None
                except (ElatecError, SerialCommunicationError, ValueError) as exc:
                    # Session is optional — keep application block capture.
                    errors.append(f"session read failed: {exc}")
                    session_bytes = None

            full_dump: bytes | None = None
            if self.config.include_full_dump:
                progress(CapturePhase.EEPROM, message="EEPROM")
                try:
                    self._ensure_selected(client, uid)
                    samples = max(1, int(self.config.full_dump_samples or 1))
                    dumps: list[bytes] = []
                    for index in range(samples):
                        dumps.append(self._read_full_dump(client, ntag, uid))
                        if index + 1 < samples:
                            self._sleep(0.05)
                    if len({d.hex() for d in dumps}) != 1:
                        errors.append("full dump samples differ")
                    full_dump = dumps[0]
                except (ElatecError, SerialCommunicationError, ValueError) as exc:
                    # Full dump is best-effort; application block is enough for OK.
                    errors.append(f"full dump failed: {exc}")
                    full_dump = None

            progress(CapturePhase.SAVING, message="SAVING")
            directory = create_capture_directory(Path(self.config.capture_root), uid)
            (directory / "application_block.bin").write_bytes(app)
            write_json(
                directory / "application_block.json",
                {
                    "uid": uid,
                    "get_version": get_version,
                    "raw_hex": app_hex,
                    "start_page": EEPROM_WATCH_START_PAGE,
                    "end_page": EEPROM_WATCH_END_PAGE,
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
                write_json(
                    directory / "session.json",
                    {
                        "uid": uid,
                        "sample_count": len(session_samples),
                        "registers": {
                            name: f"0x{session_bytes[i]:02X}"
                            for i, name in enumerate(SESSION_REGISTER_NAMES)
                            if i < len(session_bytes)
                        },
                        "raw_hex": session_bytes.hex(" ").upper(),
                        "samples_hex": [
                            sample.hex(" ").upper() for sample in session_samples
                        ],
                    },
                )
                required.append("session.json")

            if full_dump is not None:
                (directory / "dump.bin").write_bytes(full_dump)
                required.append("dump.bin")
                pages = {
                    f"0x{page:02X}": full_dump[page * 4 : (page + 1) * 4]
                    .hex(" ")
                    .upper()
                    for page in range(FULL_DUMP_START_PAGE, FULL_DUMP_END_PAGE + 1)
                }
                write_json(
                    directory / "dump.json",
                    {
                        "uid": uid,
                        "get_version": get_version,
                        "start_page": FULL_DUMP_START_PAGE,
                        "end_page": FULL_DUMP_END_PAGE,
                        "size_bytes": len(full_dump),
                        "raw_hex": full_dump.hex(" ").upper(),
                        "pages": pages,
                    },
                )
                required.append("dump.json")

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
                "include_session": session_bytes is not None,
                "include_full_dump": full_dump is not None,
                "full_dump_pages": (
                    f"0x{FULL_DUMP_START_PAGE:02X}-0x{FULL_DUMP_END_PAGE:02X}"
                    if full_dump is not None
                    else None
                ),
                "port": port,
            }
            write_json(directory / "metadata.json", metadata)
            required.append("metadata.json")

            progress(CapturePhase.VERIFYING, message="VERIFYING")
            hashes = verify_artifacts(directory, required)
            hashes["application_block_bytes"] = sha256_bytes(app)
            if full_dump is not None:
                hashes["dump_bytes"] = sha256_bytes(full_dump)

            status = (
                FinishStatus.COMPLETED_WITH_ERRORS
                if errors
                else FinishStatus.COMPLETED_SUCCESSFULLY
            )
            metadata["finish_status"] = status.value
            metadata["sha256"] = hashes

            # One tag sniff → one tar: /home/sniffer/capture/DDMMYYYY_HH_MM.tar
            export_tar: str | None = None
            export_root = self.config.export_bundle_root
            planned_tar: Path | None = None
            if export_root:
                try:
                    planned_tar = resolve_export_tar_path(Path(export_root))
                    metadata["export_bundle"] = str(planned_tar)
                except OSError as exc:
                    errors.append(f"export bundle path failed: {exc}")
                    status = FinishStatus.COMPLETED_WITH_ERRORS
                    metadata["finish_status"] = status.value
                    metadata["export_bundle_error"] = str(exc)
                    planned_tar = None

            write_json(directory / "metadata.json", metadata)
            (directory / "report.txt").write_text(
                f"UID: {uid}\n"
                f"GET_VERSION: {get_version}\n"
                f"Status: {status.value}\n"
                f"Application: {app_hex}\n"
                f"Session: "
                f"{session_bytes.hex(' ').upper() if session_bytes else 'n/a'}\n"
                f"Full dump: "
                f"{'yes (' + str(len(full_dump)) + ' B)' if full_dump else 'no'}\n"
                f"Export: {metadata.get('export_bundle') or 'n/a'}\n",
                encoding="utf-8",
            )

            if planned_tar is not None:
                progress(CapturePhase.SAVING, message="EXPORT TAR")
                try:
                    tar_path = pack_capture_export(
                        directory,
                        tar_path=planned_tar,
                    )
                    export_tar = str(tar_path)
                    emit(
                        "export_bundled",
                        uid=uid,
                        path=export_tar,
                    )
                except (OSError, FileNotFoundError, tarfile.TarError) as exc:
                    errors.append(f"export bundle failed: {exc}")
                    status = FinishStatus.COMPLETED_WITH_ERRORS
                    metadata["finish_status"] = status.value
                    metadata["export_bundle_error"] = str(exc)
                    metadata.pop("export_bundle", None)
                    write_json(directory / "metadata.json", metadata)

            append_index(
                data_root,
                {
                    "timestamp": metadata["finished_at"],
                    "uid": uid,
                    "get_version": get_version,
                    "finish_status": status.value,
                    "directory": str(directory),
                    "duplicate": False,
                    "application_sha256": hashes.get("application_block.bin", ""),
                    "dump_sha256": hashes.get("dump.bin", ""),
                    "export_bundle": export_tar or "",
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
