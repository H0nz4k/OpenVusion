from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any, Callable

from .collector_service import CollectorService
from .configuration import load_config
from .logging_setup import log_event, setup_logging
from .models import FIELD_ACTIVE_STATES, SWEETP_STATES, AppState
from .reader_detection import scan_readers
from .state import AppStateMachine
from .storage import prepare_storage, storage_status
from .sweetp_service import SweetPService
from .system_info import request_shutdown
from .ui import HeadlessUI, TouchUI, UiAction


class HWSniffApp:
    def __init__(
        self,
        config_path: Path | None = None,
        *,
        config: dict[str, Any] | None = None,
        headless: bool = False,
        list_ports: Callable | None = None,
        client_factory: Callable | None = None,
    ) -> None:
        self.config = config or load_config(config_path)
        self.state = AppStateMachine()
        self.events: queue.Queue = queue.Queue()
        self.logger = setup_logging(Path(self.config["log_root"]))
        self.ui = HeadlessUI(self.config) if headless else TouchUI(self.config)
        self.collector = CollectorService(
            self.events, client_factory=client_factory
        )
        self.sweetp = SweetPService(
            self.events, client_factory=client_factory
        )
        self._list_ports = list_ports
        self._client_factory = client_factory
        self._selected_port: str | None = None
        self._candidates = []
        self._banner_until = 0.0
        self._running = False
        self._sweetp_session = False

    def initialize(self) -> None:
        self.state.set_state(AppState.INITIALIZING)
        prepare_storage(
            Path(self.config["data_root"]),
            Path(self.config["capture_root"]),
            Path(self.config["log_root"]),
        )
        ok, text, _free = storage_status(
            Path(self.config["data_root"]),
            minimum_free_mb=int(
                (self.config.get("collector") or {}).get("minimum_free_space_mb", 1024)
            ),
        )
        self.state.update(storage_text=text)
        if not ok:
            self.state.set_state(AppState.STORAGE_ERROR, storage_text=text)
            return
        self.refresh_reader()

    def refresh_reader(self) -> None:
        previous = self.state.get().state
        keep_sweetp = previous in SWEETP_STATES
        self.state.set_state(AppState.READER_SEARCH)
        candidates = scan_readers(
            self.config,
            list_ports=self._list_ports,
            client_factory=self._client_factory,
        )
        self._candidates = candidates
        verified = [c for c in candidates if c.verified]
        log_event(
            self.logger,
            "reader_scan",
            count=len(candidates),
            verified=len(verified),
            devices=[c.device for c in candidates],
        )
        if not verified:
            self._selected_port = None
            self.state.set_state(
                AppState.READER_MISSING,
                reader_label="Připojte ELATEC čtečku",
            )
            return
        if len(verified) > 1:
            self._selected_port = None
            self.state.set_state(
                AppState.MULTIPLE_READERS,
                reader_label="Vyberte čtečku",
                candidates=[c.label for c in verified],
            )
            return
        chosen = verified[0]
        self._selected_port = chosen.device
        if keep_sweetp and previous == AppState.SWEETP_READER_ERROR:
            self.state.set_state(
                AppState.SWEETP_READER_ERROR,
                reader_label=f"READER READY: {chosen.device}",
                message="SWEETP READER ERROR",
                progress="Čtečka znovu nalezena — ZNOVU",
            )
            return
        self.state.set_state(
            AppState.READY,
            reader_label=f"READER READY: {chosen.device}",
            candidates=[],
        )

    def start_collection(self) -> None:
        if self.sweetp.running or self.state.get().state in SWEETP_STATES:
            return
        self.refresh_reader()
        snap = self.state.get()
        if snap.state != AppState.READY or not self._selected_port:
            return
        ok, text, _ = storage_status(
            Path(self.config["data_root"]),
            minimum_free_mb=int(
                (self.config.get("collector") or {}).get("minimum_free_space_mb", 1024)
            ),
        )
        self.state.update(storage_text=text)
        if not ok:
            self.state.set_state(AppState.STORAGE_ERROR, storage_text=text)
            return
        self.state.set_state(
            AppState.STARTING,
            message="SNIFFING…",
            progress="Spouštím sběr…",
            banner=None,
            capture_step=0,
            capture_step_total=6,
            capture_step_label="STARTING",
        )
        self.collector.start(self._selected_port, self.config)
        self._set_waiting_for_tag()
        log_event(self.logger, "start", port=self._selected_port)

    def _set_waiting_for_tag(self) -> None:
        self.state.set_state(
            AppState.WAITING_FOR_TAG,
            message="SNIFFING ACTIVE",
            progress="Přiložte štítek",
            banner=None,
            capture_step=1,
            capture_step_total=6,
            capture_step_label="WAITING",
        )

    def _set_capture_step(
        self,
        state: AppState,
        *,
        step: int,
        label: str,
        progress: str,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        kwargs: dict[str, Any] = {
            "progress": progress,
            "capture_step": step,
            "capture_step_total": 6,
            "capture_step_label": label,
        }
        if message is not None:
            kwargs["message"] = message
        kwargs.update(extra)
        self.state.set_state(state, **kwargs)

    def _apply_sweetp_live(self, payload: dict[str, Any]) -> None:
        quality = float(payload.get("current_quality") or 0.0)
        position_ok = bool(payload.get("position_ok"))
        poor = bool(payload.get("poor"))
        uid = payload.get("dominant_uid") or self.state.get().last_uid
        if position_ok:
            state = AppState.SWEETP_GOOD_POSITION
            message = "POSITION OK"
            banner = "ok"
        elif poor:
            state = AppState.SWEETP_UNSTABLE_POSITION
            message = "SWEETP LIVE"
            banner = "error"
        else:
            state = AppState.SWEETP_CHECKING
            message = "SWEETP LIVE"
            banner = None
        self.state.set_state(
            state,
            message=message,
            banner=banner,
            last_uid=uid or "—",
            progress=f"{quality:.0f}%",
            sweetp_current_quality=quality,
            sweetp_best_quality=float(payload.get("best_quality") or 0.0),
            sweetp_trend=str(payload.get("trend") or "stable"),
            sweetp_window_successes=int(payload.get("window_successes") or 0),
            sweetp_window_total=int(payload.get("window_total") or 0),
            sweetp_total_successes=int(payload.get("total_successes") or 0),
            sweetp_total_failures=int(payload.get("total_failures") or 0),
            sweetp_dominant_uid=str(payload.get("dominant_uid") or ""),
            sweetp_uid_consistency=float(payload.get("uid_consistency") or 0.0),
            sweetp_average_latency_ms=payload.get("average_latency_ms"),
            sweetp_stable_duration_ms=int(payload.get("stable_duration_ms") or 0),
            sweetp_enough_samples=bool(payload.get("enough_samples")),
            sweetp_position_ok=position_ok,
            sweetp_latency_available=bool(payload.get("latency_available")),
            sweetp_successes=int(payload.get("window_successes") or 0),
            sweetp_total=int(payload.get("window_total") or 0),
        )

    def stop_collection(self) -> None:
        self.state.set_state(AppState.STOPPING)
        self.collector.stop()
        self.state.set_state(AppState.READY if self._selected_port else AppState.READER_MISSING)
        log_event(self.logger, "stop")

    def start_sweetp(self) -> None:
        if self.collector.running:
            return
        if self.state.get().state != AppState.READY:
            return
        # Re-verify reader; SweetP does not require capture storage.
        self.refresh_reader()
        snap = self.state.get()
        if snap.state == AppState.MULTIPLE_READERS:
            return
        if snap.state != AppState.READY or not self._selected_port:
            return
        self.state.set_state(AppState.SWEETP_STARTING, banner=None, progress="")
        self._sweetp_session = True
        self.sweetp.start(self._selected_port, self.config)
        log_event(self.logger, "sweetp_start", port=self._selected_port)

    def stop_sweetp(self, *, cancelled: bool = True) -> None:
        self._sweetp_session = False
        if self.sweetp.running:
            self.sweetp.cancel()
        # Drop late worker events so a finishing probe cannot re-enter SweetP UI.
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        if cancelled:
            self.state.set_state(AppState.SWEETP_CANCELLED, banner=None)
        self.state.set_state(
            AppState.READY if self._selected_port else AppState.READER_MISSING,
            banner=None,
            progress="",
            sweetp_quality="",
            sweetp_attempt=0,
            sweetp_total=0,
            sweetp_successes=0,
            sweetp_current_quality=0.0,
            sweetp_best_quality=0.0,
            sweetp_trend="stable",
            sweetp_window_successes=0,
            sweetp_window_total=0,
            sweetp_total_successes=0,
            sweetp_total_failures=0,
            sweetp_dominant_uid="",
            sweetp_uid_consistency=0.0,
            sweetp_average_latency_ms=None,
            sweetp_stable_duration_ms=0,
            sweetp_enough_samples=False,
            sweetp_position_ok=False,
            sweetp_latency_available=False,
            message="READY",
        )
        log_event(
            self.logger,
            "sweetp_cancelled" if cancelled else "sweetp_finished",
            cancelled=cancelled,
        )

    def handle_action(self, action: UiAction) -> None:
        name = action.name
        if name == "start":
            self.start_collection()
        elif name == "stop":
            self.stop_collection()
        elif name == "sweetp":
            self.start_sweetp()
        elif name == "sweetp_cancel":
            self.stop_sweetp(cancelled=True)
        elif name == "sweetp_done":
            self.stop_sweetp(cancelled=False)
        elif name == "sweetp_retry":
            if self.sweetp.running:
                self.sweetp.cancel()
            self.refresh_reader()
            if self._selected_port and self.state.get().state in (
                AppState.READY,
                AppState.SWEETP_READER_ERROR,
            ):
                self._sweetp_session = True
                self.state.set_state(AppState.SWEETP_STARTING, banner=None)
                self.sweetp.start(self._selected_port, self.config)
                log_event(self.logger, "sweetp_start", port=self._selected_port, retry=True)
        elif name == "retry":
            self.refresh_reader()
        elif name == "select":
            index = int((action.payload or {}).get("index", 0))
            verified = [c for c in self._candidates if c.verified]
            if 0 <= index < len(verified):
                self._selected_port = verified[index].device
                self.state.set_state(
                    AppState.READY,
                    reader_label=f"READER READY: {self._selected_port}",
                )
        elif name == "shutdown":
            if self.sweetp.running or self.collector.running:
                return
            self.state.set_state(AppState.SHUTDOWN_CONFIRM)
        elif name == "shutdown_cancel":
            self.state.set_state(AppState.READY)
        elif name == "shutdown_confirm":
            log_event(self.logger, "shutdown")
            request_shutdown()
        elif name == "quit":
            self._running = False

    def handle_event(self, name: str, payload: dict[str, Any]) -> None:
        if name.startswith("sweetp_") and name not in (
            "sweetp_cancelled",
            "sweetp_stopped",
            "sweetp_started",
        ):
            if not self._sweetp_session:
                return
        if name == "sweetp_waiting":
            self.state.set_state(
                AppState.SWEETP_WAITING_FOR_TAG,
                message="SWEETP LIVE",
                progress="Hledejte polohu…",
                banner=None,
            )
        elif name == "sweetp_live":
            self._apply_sweetp_live(payload)
        elif name in (
            "sweetp_quality_changed",
            "sweetp_trend_changed",
            "sweetp_good_position_entered",
            "sweetp_good_position_lost",
            "sweetp_sample",
            "sweetp_finished",
        ):
            log_event(self.logger, name, **payload)
        elif name == "sweetp_reader_error":
            self.state.set_state(
                AppState.SWEETP_READER_ERROR,
                message="SWEETP READER ERROR",
                banner="error",
                progress=str(payload.get("error") or "")[:40],
            )
            log_event(self.logger, "sweetp_reader_error", **payload)
        elif name == "sweetp_cancelled":
            log_event(self.logger, "sweetp_cancelled", **payload)
        elif name == "sweetp_stopped":
            pass
        # Legacy one-shot events ignored in live mode.
        elif name in ("sweetp_checking", "sweetp_attempt", "sweetp_result"):
            pass
        elif name in ("collector_started", "loop_started"):
            if self.collector.running and self.state.get().state in FIELD_ACTIVE_STATES:
                self._set_waiting_for_tag()
        elif name == "duplicate_skipped":
            self._set_capture_step(
                AppState.WARNING,
                step=6,
                label="DUPLICATE",
                progress="Štítek už je v indexu — oddalte",
                message="DUPLICATE",
                last_uid=payload.get("uid") or self.state.get().last_uid,
                banner="error",
            )
            self._banner_until = time.monotonic() + float(
                (self.config.get("ui") or {}).get("error_display_seconds", 3.0)
            )
            log_event(self.logger, "duplicate_skipped", **payload)
        elif name == "tag_detected":
            self._set_capture_step(
                AppState.TAG_DETECTED,
                step=2,
                label="IDENTIFICATION",
                progress="TAG DETECTED — čtu…",
                message="TAG DETECTED",
                last_uid=payload.get("uid") or "—",
            )
        elif name == "phase_identification":
            detail = payload.get("message") or "IDENTIFICATION"
            self._set_capture_step(
                AppState.READING_IDENTIFICATION,
                step=2,
                label="IDENTIFICATION",
                progress=str(detail),
                message="READING 1/5",
            )
        elif name == "phase_eeprom":
            self._set_capture_step(
                AppState.READING_EEPROM,
                step=3,
                label="EEPROM",
                progress=payload.get("message") or "EEPROM",
                message="READING 2/5",
            )
        elif name == "phase_application":
            sample = payload.get("sample_index")
            total = payload.get("sample_total")
            if sample and total:
                detail = f"APPLICATION {sample}/{total}"
            else:
                detail = payload.get("message") or "APPLICATION BLOCK"
            self._set_capture_step(
                AppState.READING_APPLICATION,
                step=3,
                label="APPLICATION",
                progress=str(detail),
                message="READING 2/5",
            )
        elif name == "phase_session":
            self._set_capture_step(
                AppState.READING_SESSION,
                step=4,
                label="SESSION",
                progress=payload.get("message") or "SESSION",
                message="READING 3/5",
            )
        elif name == "phase_verifying":
            self._set_capture_step(
                AppState.VERIFYING,
                step=5,
                label="VERIFYING",
                progress="VERIFYING",
                message="READING 4/5",
            )
        elif name == "phase_saving":
            self._set_capture_step(
                AppState.SAVING,
                step=6,
                label="SAVING",
                progress="SAVING",
                message="READING 5/5",
            )
        elif name == "capture_result":
            snap = self.state.get()
            if payload.get("ok"):
                self.state.update(
                    ok_count=snap.ok_count + 1,
                    last_uid=payload.get("uid") or snap.last_uid,
                    banner="ok",
                )
                self._set_capture_step(
                    AppState.SUCCESS,
                    step=6,
                    label="DONE",
                    progress="Oddalte štítek",
                    message=f"CAPTURE OK  {payload.get('uid') or ''}",
                )
                self._banner_until = time.monotonic() + float(
                    (self.config.get("ui") or {}).get("success_display_seconds", 1.5)
                )
            else:
                self.state.update(error_count=snap.error_count + 1, banner="error")
                err = "; ".join(payload.get("errors") or ["unknown"])
                self._set_capture_step(
                    AppState.FAILURE,
                    step=6,
                    label="ERROR",
                    progress=err[:40],
                    message="CAPTURE INCOMPLETE",
                )
                self._banner_until = time.monotonic() + float(
                    (self.config.get("ui") or {}).get("error_display_seconds", 3.0)
                )
            log_event(self.logger, "capture_result", **payload)
        elif name in ("loop_error", "collector_fatal"):
            self.state.set_state(
                AppState.READER_DISCONNECTED,
                message="READER DISCONNECTED",
                banner="error",
            )
            log_event(self.logger, name, **payload)
        elif name == "collector_stopped":
            if self.state.get().state == AppState.STOPPING:
                self.state.set_state(AppState.READY)

    def pump(self) -> None:
        # Bound work per frame so a busy collector cannot stall the UI thread.
        for _ in range(64):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event.name, event.payload)

        if self._banner_until and time.monotonic() >= self._banner_until:
            self._banner_until = 0.0
            if self.collector.running:
                self.state.update(banner=None)
                self._set_waiting_for_tag()
            elif self.state.get().state not in SWEETP_STATES:
                self.state.update(banner=None)

        for action in self.ui.poll_actions():
            self.handle_action(action)
        self.ui.draw(self.state.get())

    def close(self) -> None:
        if self.sweetp.running:
            self.sweetp.cancel()
        if self.collector.running:
            self.collector.stop()
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()
        self.ui.stop()

    def run(self) -> int:
        self._running = True
        self.state.set_state(AppState.BOOTING)
        self.ui.start()
        try:
            self.initialize()
            log_event(self.logger, "boot", config_keys=list(self.config.keys()))
            while self._running:
                self.pump()
                time.sleep(0.03)
        finally:
            self.close()
            self.state.set_state(AppState.STOPPED)
        return 0
