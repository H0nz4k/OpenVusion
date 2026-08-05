"""Collector interface for HWSniff v2 — shared ElaTool CaptureProbe engine.

MockCollector remains for unit tests / offline LED validation.
Production uses CaptureCollector → FieldCollector → readonly_capture.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .state import READ_PHASE_STEPS, CollectorOutcome, DipMode

log = logging.getLogger(__name__)


@dataclass
class CollectorProgress:
    phase: str = ""
    message: str = ""
    step: int = 0  # 0..6 READ progress
    current: int = 0
    total: int = 0


@dataclass
class CollectorResult:
    outcome: CollectorOutcome
    message: str = ""
    mode: DipMode | None = None
    uid: str | None = None
    directory: str | None = None
    phase_status: dict[str, str] = field(default_factory=dict)
    errors: list[Any] = field(default_factory=list)
    fatal_save: bool = False


class CollectorService(Protocol):
    def start(
        self,
        mode: DipMode,
        *,
        port: str | None = None,
        summary_extra: dict[str, Any] | None = None,
        artifact_files: dict[str, str] | None = None,
    ) -> None: ...

    def request_stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def get_progress(self) -> CollectorProgress: ...

    def get_result(self) -> CollectorResult | None: ...

    def tick(self, now: float | None = None) -> None: ...


class MockCollector:
    """Simulated 6-phase capture for tests — tick-driven, no worker thread."""

    PHASES = (
        "uid_confirm",
        "identification",
        "eeprom",
        "application",
        "session",
        "verification",
    )

    def __init__(
        self,
        *,
        work_seconds: float = 1.2,
        save_seconds: float = 0.2,
        phase_seconds: float = 0.15,
        outcome: CollectorOutcome | str = CollectorOutcome.SUCCESS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.work_seconds = work_seconds
        self.save_seconds = save_seconds
        self.phase_seconds = phase_seconds
        if isinstance(outcome, str):
            outcome = CollectorOutcome(outcome)
        self.default_outcome = outcome
        self._clock = clock
        self._running = False
        self._stop = False
        self._progress = CollectorProgress()
        self._result: CollectorResult | None = None
        self._mode: DipMode | None = None
        self._t0 = 0.0
        self.on_phase: Callable[[str], None] | None = None
        self.on_phase_started: Callable[[str], None] | None = None
        self.on_reader_complete: Callable[[], None] | None = None
        self.on_save_started: Callable[[], None] | None = None
        self._phase_idx = -1
        self._reader_done = False
        self._saving = False
        self.summary_extra: dict[str, Any] | None = None
        self.artifact_files: dict[str, str] | None = None

    def start(
        self,
        mode: DipMode,
        *,
        port: str | None = None,
        summary_extra: dict[str, Any] | None = None,
        artifact_files: dict[str, str] | None = None,
    ) -> None:
        del port
        if self._running:
            return
        self._stop = False
        self._result = None
        self._mode = mode
        self.summary_extra = dict(summary_extra) if summary_extra else None
        self.artifact_files = dict(artifact_files) if artifact_files else None
        self._running = True
        self._t0 = self._clock()
        self._phase_idx = -1
        self._reader_done = False
        self._saving = False
        self._progress = CollectorProgress()

    def request_stop(self) -> None:
        self._stop = True

    def is_running(self) -> bool:
        return self._running

    def get_progress(self) -> CollectorProgress:
        return self._progress

    def get_result(self) -> CollectorResult | None:
        return self._result

    def tick(self, now: float | None = None) -> None:
        if not self._running:
            return
        now = self._clock() if now is None else now
        if self._stop:
            self._finish(CollectorOutcome.CANCELLED, "stopped")
            return
        elapsed = now - self._t0
        if not self._reader_done:
            idx = int(elapsed / self.phase_seconds)
            if idx > self._phase_idx and idx < len(self.PHASES):
                self._phase_idx = idx
                name = self.PHASES[idx]
                self._set_phase(name, step=READ_PHASE_STEPS[name])
                if self.on_phase_started:
                    try:
                        self.on_phase_started(name)
                    except Exception:  # noqa: BLE001
                        log.exception("on_phase_started failed")
            if elapsed < len(self.PHASES) * self.phase_seconds:
                return
            self._reader_done = True
            self._progress = CollectorProgress(
                phase="reader_complete", message="reader_complete", step=6
            )
            if self.on_reader_complete:
                try:
                    self.on_reader_complete()
                except Exception:  # noqa: BLE001
                    log.exception("on_reader_complete failed")
            return
        if not self._saving:
            self._saving = True
            self._set_phase("saving", step=6)
            if self.on_save_started:
                try:
                    self.on_save_started()
                except Exception:  # noqa: BLE001
                    log.exception("on_save_started failed")
            return
        # After save_seconds from reader_done mark
        save_start = len(self.PHASES) * self.phase_seconds
        if elapsed < save_start + self.save_seconds:
            return
        self._finish(self.default_outcome, "mock complete")

    def _set_phase(self, phase: str, *, step: int) -> None:
        self._progress = CollectorProgress(phase=phase, message=phase, step=step)
        if self.on_phase:
            try:
                self.on_phase(phase)
            except Exception:  # noqa: BLE001
                log.exception("on_phase callback failed")

    def _finish(self, outcome: CollectorOutcome, message: str) -> None:
        self._result = CollectorResult(
            outcome=outcome,
            message=message,
            mode=self._mode,
            uid="MOCKUID",
            directory=None,
            fatal_save=outcome == CollectorOutcome.FAILED and "save" in message.lower(),
        )
        self._running = False


class CaptureCollector:
    """Worker-thread wrapper around ElaTool FieldCollector (shared CaptureProbe)."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client_factory: Callable | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._collector = None
        self._running = False
        self._result: CollectorResult | None = None
        self._progress = CollectorProgress()
        self._mode: DipMode | None = None
        self._lock = threading.Lock()
        self._reader_complete = False
        self.on_phase: Callable[[str], None] | None = None
        self.on_phase_started: Callable[[str], None] | None = None
        self.on_reader_complete: Callable[[], None] | None = None
        self.on_save_started: Callable[[], None] | None = None
        self.on_error: Callable[[dict[str, Any]], None] | None = None
        self._summary_extra: dict[str, Any] | None = None
        self._artifact_files: dict[str, str] | None = None

    def start(
        self,
        mode: DipMode,
        *,
        port: str | None = None,
        summary_extra: dict[str, Any] | None = None,
        artifact_files: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            if self._running:
                return
            if not port:
                self._result = CollectorResult(
                    outcome=CollectorOutcome.FAILED,
                    message="no_reader_port",
                    mode=mode,
                )
                return
            self._mode = mode
            self._summary_extra = dict(summary_extra) if summary_extra else None
            self._artifact_files = dict(artifact_files) if artifact_files else None
            self._result = None
            self._reader_complete = False
            self._progress = CollectorProgress()
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                args=(port,),
                name="hwsniff-capture",
                daemon=True,
            )
            self._thread.start()

    def request_stop(self) -> None:
        coll = self._collector
        if coll is not None:
            coll.request_stop()

    def is_running(self) -> bool:
        return self._running

    def get_progress(self) -> CollectorProgress:
        return self._progress

    def get_result(self) -> CollectorResult | None:
        return self._result

    def tick(self, now: float | None = None) -> None:
        del now  # worker-driven

    def _run(self, port: str) -> None:
        import dataclasses

        from elatec_uid_tool.field_collector import (
            CapturePhase,
            CollectorConfig,
            FieldCollector,
            FinishStatus,
        )

        coll_cfg = self.config.get("collector") or {}
        reader_cfg = self.config.get("reader") or {}
        try:
            cfg_kwargs: dict[str, Any] = {
                "capture_root": self.config["capture_root"],
                "data_root": self.config.get("data_root"),
                "application_samples": int(coll_cfg.get("application_samples", 3)),
                "full_dump_samples": int(coll_cfg.get("full_dump_samples", 1)),
                "session_duration_seconds": float(
                    coll_cfg.get(
                        "session_duration_seconds",
                        reader_cfg.get("session_seconds", 2.0),
                    )
                ),
                "session_interval_ms": float(
                    coll_cfg.get(
                        "session_interval_ms",
                        reader_cfg.get("session_interval_ms", 50),
                    )
                ),
                "allow_duplicate": bool(coll_cfg.get("allow_duplicate", True)),
                "wait_for_removal": False,
                "handshake_timeout_seconds": float(
                    reader_cfg.get("handshake_timeout_seconds", 2)
                ),
                "include_session": bool(coll_cfg.get("include_session", True)),
                "include_full_dump": bool(coll_cfg.get("include_full_dump", True)),
                "export_bundle_root": coll_cfg.get(
                    "export_bundle_root", "/var/lib/hwsniff/export"
                ),
                "export_bundle_mirror_root": coll_cfg.get(
                    "export_bundle_mirror_root"
                ),
                "include_logs_in_bundle": bool(
                    coll_cfg.get("include_logs_in_bundle", False)
                ),
                "log_root": self.config.get("log_root"),
                "phase_retry_count": int(
                    coll_cfg.get(
                        "phase_retry_count", reader_cfg.get("retry_count", 3)
                    )
                ),
                "phase_retry_delay_ms": float(
                    coll_cfg.get(
                        "phase_retry_delay_ms",
                        reader_cfg.get("retry_delay_ms", 150),
                    )
                ),
                "tag_acquire_timeout_seconds": float(
                    coll_cfg.get("tag_acquire_timeout_seconds", 30)
                ),
                "capture_timeout_seconds": float(
                    coll_cfg.get("capture_timeout_seconds", 180)
                ),
                "raw_trace": bool(
                    coll_cfg.get("raw_trace", reader_cfg.get("raw_trace", True))
                ),
                "confirm_reads": int(
                    coll_cfg.get(
                        "confirm_reads", reader_cfg.get("confirm_reads", 3)
                    )
                ),
                "label": "hwsniff-v2",
                "state": "field",
                "summary_extra": self._summary_extra,
                "artifact_files": self._artifact_files,
            }
            # Editable install on Pi may lag behind HWSniff; only pass known fields.
            known = {f.name for f in dataclasses.fields(CollectorConfig)}
            missing = sorted(k for k in ("summary_extra", "artifact_files") if k not in known)
            if missing:
                log.warning(
                    "CollectorConfig missing %s — reinstall elatec_uid_tool "
                    "from /opt/Sniff/_vendor/ElaTool (SweetP summary/trace skipped)",
                    ",".join(missing),
                )
            collector_config = CollectorConfig(
                **{k: v for k, v in cfg_kwargs.items() if k in known}
            )
            collector = FieldCollector(
                collector_config,
                client_factory=self._client_factory,
            )
            self._collector = collector

            def on_event(name: str, payload: dict[str, Any]) -> None:
                if name == "phase_started":
                    phase = str(payload.get("phase") or "")
                    step = READ_PHASE_STEPS.get(phase, self._progress.step)
                    self._progress = CollectorProgress(
                        phase=phase, message="started", step=step
                    )
                    if self.on_phase_started:
                        self.on_phase_started(phase)
                    if self.on_phase:
                        self.on_phase(phase)
                elif name == "phase_progress":
                    self._progress = CollectorProgress(
                        phase=str(payload.get("phase") or ""),
                        message="progress",
                        step=READ_PHASE_STEPS.get(
                            str(payload.get("phase") or ""), self._progress.step
                        ),
                        current=int(payload.get("current") or 0),
                        total=int(payload.get("total") or 0),
                    )
                elif name == "phase_complete":
                    phase = str(payload.get("phase") or "")
                    step = READ_PHASE_STEPS.get(phase, self._progress.step)
                    self._progress = CollectorProgress(
                        phase=phase,
                        message=str(payload.get("status") or "ok"),
                        step=step,
                    )
                elif name == "phase" and payload.get("detail") == "started":
                    phase = str(payload.get("key") or "")
                    step = READ_PHASE_STEPS.get(phase, self._progress.step)
                    self._progress = CollectorProgress(
                        phase=phase, message="started", step=step
                    )
                    if self.on_phase_started:
                        self.on_phase_started(phase)

            def on_progress(progress) -> None:
                if progress.phase == CapturePhase.SAVING:
                    if not self._reader_complete:
                        self._reader_complete = True
                        if self.on_reader_complete:
                            self.on_reader_complete()
                    self._progress = CollectorProgress(
                        phase="saving", message="saving", step=6
                    )
                    if self.on_save_started:
                        self.on_save_started()

            result = collector.run_once(
                port, on_progress=on_progress, on_event=on_event
            )
            if not self._reader_complete:
                self._reader_complete = True
                if self.on_reader_complete:
                    self.on_reader_complete()

            outcome = self._map_outcome(result.finish_status)
            fatal_save = any(
                "persistence" in str(e).lower() or "export" in str(e).lower()
                for e in (result.errors or [])
            ) and outcome == CollectorOutcome.FAILED

            self._result = CollectorResult(
                outcome=outcome,
                message=result.finish_status.value,
                mode=self._mode,
                uid=result.uid,
                directory=result.directory,
                phase_status=dict(result.phase_status or {}),
                errors=list(result.errors or []),
                fatal_save=fatal_save,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("CaptureCollector fatal")
            tb = traceback.format_exc()
            err = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "traceback": tb,
            }
            if self.on_error:
                try:
                    self.on_error(err)
                except Exception:  # noqa: BLE001
                    pass
            self._result = CollectorResult(
                outcome=CollectorOutcome.FAILED,
                message=f"{type(exc).__name__}: {exc}",
                mode=self._mode,
                fatal_save=True,
                errors=[err],
            )
        finally:
            self._collector = None
            self._running = False

    @staticmethod
    def _map_outcome(finish_status) -> CollectorOutcome:
        from elatec_uid_tool.field_collector import FinishStatus
        from elatec_uid_tool.readonly_capture.status import OverallStatus

        # finish_status is FinishStatus; bridge maps OverallStatus too
        value = finish_status.value if hasattr(finish_status, "value") else str(finish_status)
        if finish_status == FinishStatus.ABORTED or value == "aborted":
            return CollectorOutcome.CANCELLED
        if finish_status == FinishStatus.COMPLETED_SUCCESSFULLY:
            return CollectorOutcome.SUCCESS
        if finish_status in (
            FinishStatus.COMPLETED_WITH_ERRORS,
            FinishStatus.PARTIAL,
            FinishStatus.DUPLICATE_SKIPPED,
        ):
            return CollectorOutcome.PARTIAL
        if value == OverallStatus.SUCCESS.value:
            return CollectorOutcome.SUCCESS
        if value == OverallStatus.PARTIAL.value:
            return CollectorOutcome.PARTIAL
        return CollectorOutcome.FAILED


def create_collector(
    config: dict[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    client_factory: Callable | None = None,
    force_mock: bool = False,
) -> Any:
    coll = config.get("collector") or {}
    use_mock = force_mock or bool(coll.get("use_mock")) or bool(
        config.get("gpio_prefer_mock")
    )
    if use_mock:
        mock_cfg = config.get("mock_collector") or {}
        return MockCollector(
            work_seconds=float(mock_cfg.get("work_seconds", 1.2)),
            save_seconds=float(mock_cfg.get("save_seconds", 0.2)),
            phase_seconds=float(mock_cfg.get("phase_seconds", 0.15)),
            outcome=CollectorOutcome(
                mock_cfg.get("outcome", CollectorOutcome.SUCCESS.value)
            ),
            clock=clock,
        )
    return CaptureCollector(config, client_factory=client_factory, clock=clock)
