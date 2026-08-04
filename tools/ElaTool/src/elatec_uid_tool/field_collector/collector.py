from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

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
    index_contains_uid,
    pack_capture_export,
    resolve_export_tar_path,
)

ProgressCallback = Callable[[CaptureProgress], None]
EventCallback = Callable[[str, dict[str, Any]], None]


class FieldCollector:
    """HWSniff/UI orchestrator over shared readonly_capture engine."""

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
        """One-shot capture via shared readonly_capture engine (PCSniff parity)."""
        self.clear_stop()
        self._busy.set()
        try:
            return self._run_shared_engine(
                port, on_progress=on_progress, on_event=on_event
            )
        finally:
            self._busy.clear()

    def run_once(
        self,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> FieldCaptureResult:
        """Public alias for a single-tag capture (HWSniff START workflow)."""
        return self.capture_one(
            port, on_progress=on_progress, on_event=on_event
        )

    def run_continuous(
        self,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
        on_result: Callable[[FieldCaptureResult], None] | None = None,
    ) -> None:
        """Repeat shared one-shot captures; optionally wait for tag removal."""
        self.clear_stop()

        def emit(name: str, **payload: Any) -> None:
            if on_event:
                on_event(name, payload)

        emit("loop_started", port=port)
        while not self._stop.is_set():
            try:
                result = self.capture_one(
                    port, on_progress=on_progress, on_event=on_event
                )
                if on_result:
                    on_result(result)
                if result.finish_status == FinishStatus.ABORTED and not result.uid:
                    break
                need_removal = (
                    self.config.wait_for_removal
                    and result.uid
                    and result.finish_status != FinishStatus.ABORTED
                ) or result.finish_status == FinishStatus.DUPLICATE_SKIPPED
                if need_removal and not self._stop.is_set():
                    emit("waiting_for_removal", uid=result.uid)
                    try:
                        self._wait_for_removal(port)
                    except (ElatecError, SerialCommunicationError, OSError) as exc:
                        emit("loop_error", error=str(exc))
                    finally:
                        if not self._stop.is_set():
                            emit("tag_removed", uid=result.uid)
            except (ElatecError, SerialCommunicationError, OSError) as exc:
                emit("loop_error", error=str(exc))
                emit("tag_removed", uid=None)
                self._sleep(1.0)
        emit("loop_stopped", port=port)

    def _run_shared_engine(
        self,
        port: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> FieldCaptureResult:
        """Drive CaptureProbe (same sequence/retry/persist as PCSniff)."""
        from ..readonly_capture import CaptureProbe, ProbeConfig
        from ..readonly_capture.bridge import probe_to_field_result
        from ..readonly_capture.status import OverallStatus

        def emit(name: str, **payload: Any) -> None:
            if on_event:
                on_event(name, payload)

        emit("capture_started", port=port)

        phase_map = {
            "reader_info": CapturePhase.IDENTIFICATION,
            "tag_detection": CapturePhase.IDENTIFICATION,
            "uid_confirm": CapturePhase.IDENTIFICATION,
            "identification": CapturePhase.IDENTIFICATION,
            "eeprom": CapturePhase.EEPROM,
            "application": CapturePhase.APPLICATION_BLOCK,
            "session": CapturePhase.SESSION,
            "verification": CapturePhase.VERIFYING,
        }

        def on_phase(key: str, detail: str) -> None:
            # Always forward raw phase key for HWSniff LED progress bar.
            emit("phase", key=key, detail=detail)
            phase = phase_map.get(key)
            if on_progress and phase is not None and detail != "started":
                on_progress(CaptureProgress(phase=phase, message=detail))

        data_root = Path(self.config.resolved_data_root())

        def uid_gate(uid: str) -> bool:
            if self.config.allow_duplicate:
                return True
            return not index_contains_uid(data_root, uid)

        probe = CaptureProbe(
            ProbeConfig(
                port=port,
                output=Path(self.config.capture_root),
                raw_trace=bool(self.config.raw_trace),
                tag_timeout=float(self.config.tag_acquire_timeout_seconds),
                retry_count=int(self.config.phase_retry_count),
                retry_delay_ms=float(self.config.phase_retry_delay_ms),
                session_seconds=float(self.config.session_duration_seconds),
                session_interval_ms=float(self.config.session_interval_ms),
                poll_interval_seconds=float(self.config.poll_interval_seconds),
                confirm_reads=int(self.config.confirm_reads),
                skip_eeprom=not bool(self.config.include_full_dump),
                skip_application=False,
                skip_session=not bool(self.config.include_session),
                handshake_timeout=float(self.config.handshake_timeout_seconds),
                quiet=True,
            ),
            client_factory=self._client_factory,
            sleep=self._sleep,
            stop_event=self._stop,
            on_event=lambda name, payload: emit(name, **payload),
            on_phase=on_phase,
            uid_gate=uid_gate,
        )
        result = probe.run()

        if self.config.summary_extra and result.output_dir:
            self._merge_summary_extra(Path(result.output_dir), self.config.summary_extra)

        export_tar: str | None = None
        if (
            result.uid
            and not result.duplicate
            and result.overall != OverallStatus.FAILED
            and result.output_dir
        ):
            if on_progress:
                on_progress(CaptureProgress(phase=CapturePhase.SAVING, message="SAVING"))
            export_root = self.config.export_bundle_root
            if export_root:
                try:
                    planned = resolve_export_tar_path(Path(export_root))
                    tar_path = pack_capture_export(
                        result.output_dir,
                        tar_path=planned,
                        log_root=self.config.log_root,
                        include_logs=bool(self.config.include_logs_in_bundle),
                        mirror_root=self.config.export_bundle_mirror_root,
                    )
                    export_tar = str(tar_path)
                    emit("export_bundled", path=export_tar, uid=result.uid)
                except OSError as exc:
                    result.errors.append(
                        {
                            "phase": "export",
                            "code": "persistence_error",
                            "message": f"export bundle failed: {exc}",
                        }
                    )
            try:
                append_index(
                    data_root,
                    {
                        "timestamp": self._clock(),
                        "uid": result.uid,
                        "get_version": None,
                        "finish_status": result.overall.value,
                        "directory": str(result.output_dir),
                        "duplicate": False,
                    },
                )
            except OSError as exc:
                result.errors.append(
                    {
                        "phase": "index",
                        "code": "persistence_error",
                        "message": f"index append failed: {exc}",
                    }
                )

        field = probe_to_field_result(result, export_bundle=export_tar)
        if result.aborted and not result.uid:
            field.finish_status = FinishStatus.ABORTED
            if not field.errors:
                field.errors = ["aborted before tag"]
        emit(
            "capture_finished",
            uid=field.uid,
            status=field.finish_status.value,
            directory=field.directory,
        )
        return field

    def _field_wake(self, client: Any) -> None:
        """Drop RF so a resting/HALTed tag will answer the next SearchTag."""
        try:
            client.set_rf_off()
        except (ElatecError, SerialCommunicationError, OSError, AttributeError):
            return
        self._sleep(0.05)

    def _search_tag(self, client: Any) -> TagRead | None:
        """SearchTag with RF wake â€” finds tags already sitting on the antenna."""
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

    @staticmethod
    def _merge_summary_extra(output_dir: Path, extra: dict[str, Any]) -> None:
        """Merge caller fields into summary.json before tar export."""
        import json

        path = output_dir / "summary.json"
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data.update(extra)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

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
