from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from elatec_uid_tool.field_collector import (
    CapturePhase,
    CollectorConfig,
    FieldCaptureResult,
    FieldCollector,
    FinishStatus,
)

from .models import AppEvent


PHASE_TO_EVENT = {
    CapturePhase.IDENTIFICATION: "phase_identification",
    CapturePhase.EEPROM: "phase_eeprom",
    CapturePhase.APPLICATION_BLOCK: "phase_application",
    CapturePhase.SESSION: "phase_session",
    CapturePhase.VERIFYING: "phase_verifying",
    CapturePhase.SAVING: "phase_saving",
}


class CollectorService:
    """Background worker: one START → one tag → one result → stop."""

    def __init__(
        self,
        events: queue.Queue,
        *,
        client_factory: Callable | None = None,
    ) -> None:
        self.events = events
        self._client_factory = client_factory
        self._thread: threading.Thread | None = None
        self._collector: FieldCollector | None = None
        self._port: str | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, config: dict[str, Any]) -> None:
        with self._lock:
            if self.running:
                return
            coll = config.get("collector") or {}
            # One-shot START never auto-waits for the next tag.
            collector_config = CollectorConfig(
                capture_root=config["capture_root"],
                data_root=config["data_root"],
                application_samples=int(coll.get("application_samples", 3)),
                full_dump_samples=int(coll.get("full_dump_samples", 1)),
                # Defaults aligned with verified PCSniff physical SUCCESS run.
                session_duration_seconds=float(
                    coll.get("session_duration_seconds", 2.0)
                ),
                session_interval_ms=float(coll.get("session_interval_ms", 50)),
                allow_duplicate=bool(coll.get("allow_duplicate", False)),
                wait_for_removal=False,
                handshake_timeout_seconds=float(
                    (config.get("reader") or {}).get("handshake_timeout_seconds", 2)
                ),
                include_session=bool(coll.get("include_session", True)),
                include_full_dump=bool(coll.get("include_full_dump", True)),
                export_bundle_root=coll.get(
                    "export_bundle_root", "/home/sniffer/capture"
                ),
                phase_retry_count=int(coll.get("phase_retry_count", 3)),
                phase_retry_delay_ms=float(coll.get("phase_retry_delay_ms", 150)),
                tag_acquire_timeout_seconds=float(
                    coll.get("tag_acquire_timeout_seconds", 60)
                ),
                capture_timeout_seconds=float(
                    coll.get("capture_timeout_seconds", 120)
                ),
                label="field",
                state="field",
            )
            self._collector = FieldCollector(
                collector_config,
                client_factory=self._client_factory,
            )
            self._port = port
            self._thread = threading.Thread(
                target=self._run,
                name="hwsniff-collector",
                daemon=True,
            )
            self._thread.start()
            self._emit("collector_started", port=port)

    def stop(self, *, join_timeout: float = 5.0) -> None:
        with self._lock:
            collector = self._collector
            thread = self._thread
        if collector:
            collector.request_stop()
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._collector = None
        self._emit("collector_stopped")

    def _run(self) -> None:
        assert self._collector is not None and self._port is not None
        port = self._port
        collector = self._collector

        def on_progress(progress) -> None:
            self._emit(
                PHASE_TO_EVENT.get(progress.phase, "phase"),
                message=progress.message,
                sample_index=progress.sample_index,
                sample_total=progress.sample_total,
                phase=progress.phase.value,
            )

        def on_event(name: str, payload: dict[str, Any]) -> None:
            self._emit(name, **payload)

        try:
            result = collector.run_once(
                port,
                on_progress=on_progress,
                on_event=on_event,
            )
            self._emit_result(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self._emit("collector_fatal", error=str(exc))
        finally:
            # Port/session closed by run_once context manager; drop worker refs.
            with self._lock:
                self._thread = None
                self._collector = None
            self._emit("collector_finished")

    def _emit_result(self, result: FieldCaptureResult) -> None:
        status = result.finish_status
        if status == FinishStatus.COMPLETED_SUCCESSFULLY:
            outcome = "ok"
        elif status == FinishStatus.COMPLETED_WITH_ERRORS:
            outcome = "with_errors"
        elif status == FinishStatus.DUPLICATE_SKIPPED:
            outcome = "duplicate"
        elif status == FinishStatus.ABORTED:
            outcome = "aborted"
        else:
            outcome = "failed"
        self._emit(
            "capture_result",
            uid=result.uid,
            status=status.value,
            outcome=outcome,
            directory=result.directory,
            errors=result.errors,
            duplicate=result.duplicate,
            phase_status=result.phase_status or result.metadata.get("phase_status") or {},
            export_bundle=(result.metadata or {}).get("export_bundle"),
            ok=status
            in (
                FinishStatus.COMPLETED_SUCCESSFULLY,
                FinishStatus.COMPLETED_WITH_ERRORS,
            ),
        )

    def _emit(self, name: str, **payload: Any) -> None:
        self.events.put(AppEvent(name=name, payload=payload))
