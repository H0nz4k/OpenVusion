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
    """Background worker that drives FieldCollector without blocking UI."""

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

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, config: dict[str, Any]) -> None:
        if self.running:
            return
        coll = config.get("collector") or {}
        collector_config = CollectorConfig(
            capture_root=config["capture_root"],
            data_root=config["data_root"],
            application_samples=int(coll.get("application_samples", 5)),
            full_dump_samples=int(coll.get("full_dump_samples", 0)),
            session_duration_seconds=float(coll.get("session_duration_seconds", 2.0)),
            session_interval_ms=float(coll.get("session_interval_ms", 50)),
            allow_duplicate=bool(coll.get("allow_duplicate", False)),
            wait_for_removal=bool(coll.get("wait_for_removal", True)),
            handshake_timeout_seconds=float(
                (config.get("reader") or {}).get("handshake_timeout_seconds", 2)
            ),
            include_session=bool(coll.get("include_session", True)),
            include_full_dump=bool(coll.get("include_full_dump", False)),
            export_bundle_root=coll.get(
                "export_bundle_root", "/home/sniffer/capture"
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
        if self._collector:
            self._collector.request_stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        self._thread = None
        self._emit("collector_stopped")

    def _run(self) -> None:
        assert self._collector is not None and self._port is not None

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

        def on_result(result: FieldCaptureResult) -> None:
            self._emit(
                "capture_result",
                uid=result.uid,
                status=result.finish_status.value,
                directory=result.directory,
                errors=result.errors,
                duplicate=result.duplicate,
                ok=result.finish_status
                in (
                    FinishStatus.COMPLETED_SUCCESSFULLY,
                    FinishStatus.COMPLETED_WITH_ERRORS,
                ),
            )

        try:
            self._collector.run_continuous(
                self._port,
                on_progress=on_progress,
                on_event=on_event,
                on_result=on_result,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to UI as event
            self._emit("collector_fatal", error=str(exc))

    def _emit(self, name: str, **payload: Any) -> None:
        self.events.put(AppEvent(name=name, payload=payload))
