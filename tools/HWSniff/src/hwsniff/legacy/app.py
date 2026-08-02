from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any, Callable

from ..configuration import load_config
from ..logging_setup import log_event, setup_logging
from ..reader_detection import scan_readers
from ..storage import prepare_storage, storage_status
from ..system_info import request_shutdown
from .collector_service import CollectorService
from .models import FIELD_CAPTURE_STATES, FIELD_RESULT_STATES, SWEETP_STATES, AppState
from .state import AppStateMachine
from .sweetp_service import SweetPService
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
        # START = exactly one capture. Ignore while a capture thread is alive.
        if self.collector.running:
            return
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
        self._banner_until = 0.0
        self.state.set_state(
            AppState.STARTING,
            message="SNIFFING…",
            progress="Spouštím sběr…",
            banner=None,
            capture_step=0,
            capture_step_total=7,
            capture_step_label="STARTING",
            capture_directory="",
            capture_export_bundle="",
            capture_outcome="",
            capture_phase_errors=0,
            phase_identification="",
            phase_eeprom="",
            phase_application="",
            phase_session="",
            phase_verify="",
            phase_save="",
        )
        self.collector.start(self._selected_port, self.config)
        self._set_waiting_for_tag()
        log_event(self.logger, "start", port=self._selected_port, mode="oneshot")

    def _set_waiting_for_tag(self) -> None:
        self.state.set_state(
            AppState.WAITING_FOR_TAG,
            message="SNIFFING ACTIVE",
            progress="Přiložte štítek",
            banner=None,
            capture_step=1,
            capture_step_total=7,
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
            "capture_step_total": 7,
            "capture_step_label": label,
        }
        if message is not None:
            kwargs["message"] = message
        kwargs.update(extra)
        self.state.set_state(state, **kwargs)

    def _apply_phase_status(self, phase_status: dict[str, Any]) -> dict[str, str]:
        mapping = {
            "identification": "phase_identification",
            "eeprom": "phase_eeprom",
            "application": "phase_application",
            "session": "phase_session",
            "verify": "phase_verify",
            "verification": "phase_verify",
            "save": "phase_save",
            "reader_info": "phase_identification",
        }
        updates: dict[str, str] = {}
        for key, attr in mapping.items():
            value = str(phase_status.get(key) or "")
            updates[attr] = value
        return updates

    def _show_capture_result(self, payload: dict[str, Any]) -> None:
        phase_status = payload.get("phase_status") or {}
        phase_updates = self._apply_phase_status(phase_status)
        errors = list(payload.get("errors") or [])
        outcome = str(payload.get("outcome") or "")
        uid = payload.get("uid") or self.state.get().last_uid
        directory = str(payload.get("directory") or "")
        export_bundle = str(payload.get("export_bundle") or "")
        snap = self.state.get()

        if outcome == "ok":
            state = AppState.SUCCESS
            message = "HOTOVO"
            banner = "ok"
            self.state.update(ok_count=snap.ok_count + 1)
        elif outcome in ("with_errors", "duplicate"):
            state = AppState.WARNING
            message = "HOTOVO S CHYBAMI"
            banner = "error"
            if outcome == "duplicate" and not errors:
                errors = ["Štítek už je v indexu"]
            self.state.update(error_count=snap.error_count + 1)
        else:
            state = AppState.FAILURE
            message = "SELHALO"
            banner = "error"
            self.state.update(error_count=snap.error_count + 1)

        summary = "; ".join(errors) if errors else "Všechny fáze OK"
        self._banner_until = 0.0
        self.state.set_state(
            state,
            message=message,
            progress=summary[:40],
            banner=banner,
            last_uid=uid or "—",
            capture_step=7,
            capture_step_total=7,
            capture_step_label="DONE",
            capture_directory=directory,
            capture_export_bundle=export_bundle,
            capture_outcome=outcome or ("ok" if state == AppState.SUCCESS else "failed"),
            capture_phase_errors=len(errors),
            **phase_updates,
        )

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
        elif name == "new_tag":
            if self.state.get().state in FIELD_RESULT_STATES:
                self.start_collection()
        elif name == "detail":
            if self.state.get().state in (
                AppState.SUCCESS,
                AppState.WARNING,
                AppState.FAILURE,
            ):
                snap = self.state.get()
                self.state.set_state(
                    AppState.CAPTURE_DETAIL,
                    message="DETAIL ZÁZNAMU",
                    progress=snap.capture_directory[:40] if snap.capture_directory else "",
                    banner=snap.banner,
                )
        elif name == "back":
            if self.state.get().state == AppState.CAPTURE_DETAIL:
                outcome = self.state.get().capture_outcome
                if outcome == "ok":
                    target = AppState.SUCCESS
                    message = "HOTOVO"
                elif outcome in ("with_errors", "duplicate"):
                    target = AppState.WARNING
                    message = "HOTOVO S CHYBAMI"
                else:
                    target = AppState.FAILURE
                    message = "SELHALO"
                snap = self.state.get()
                self.state.set_state(
                    target,
                    message=message,
                    progress=snap.progress,
                    banner=snap.banner,
                )
            elif self.state.get().state in FIELD_RESULT_STATES:
                self.state.set_state(
                    AppState.READY if self._selected_port else AppState.READER_MISSING,
                    banner=None,
                    progress="",
                    message="READY",
                )
        elif name == "stop":
            if self.state.get().state in FIELD_CAPTURE_STATES:
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
            if self.state.get().state in FIELD_RESULT_STATES:
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
            if self.state.get().state == AppState.STARTING:
                self._set_waiting_for_tag()
        elif name in ("waiting_for_removal", "tag_removed"):
            # One-shot START does not auto-chain to the next tag.
            log_event(self.logger, name, **payload)
        elif name == "duplicate_skipped":
            # Final outcome still arrives via capture_result.
            log_event(self.logger, "duplicate_skipped", **payload)
        elif name == "tag_detected":
            self._set_capture_step(
                AppState.TAG_DETECTED,
                step=2,
                label="IDENTIFICATION",
                progress="ČTU IDENTIFIKACI",
                message="ČTU IDENTIFIKACI",
                last_uid=payload.get("uid") or "—",
            )
        elif name == "phase_identification":
            self._set_capture_step(
                AppState.READING_IDENTIFICATION,
                step=2,
                label="IDENTIFICATION",
                progress="ČTU IDENTIFIKACI",
                message="ČTU IDENTIFIKACI",
            )
        elif name == "phase_eeprom":
            self._set_capture_step(
                AppState.READING_EEPROM,
                step=3,
                label="EEPROM",
                progress="ČTU EEPROM",
                message="ČTU EEPROM",
            )
        elif name == "phase_application":
            sample = payload.get("sample_index")
            total = payload.get("sample_total")
            detail = (
                f"ČTU APPLICATION BLOCK {sample}/{total}"
                if sample and total
                else "ČTU APPLICATION BLOCK"
            )
            self._set_capture_step(
                AppState.READING_APPLICATION,
                step=4,
                label="APPLICATION",
                progress=detail,
                message="ČTU APPLICATION BLOCK",
            )
        elif name == "phase_session":
            self._set_capture_step(
                AppState.READING_SESSION,
                step=5,
                label="SESSION",
                progress="MĚŘÍM SESSION",
                message="MĚŘÍM SESSION",
            )
        elif name == "phase_verifying":
            self._set_capture_step(
                AppState.VERIFYING,
                step=6,
                label="VERIFYING",
                progress="OVĚŘUJI",
                message="OVĚŘUJI",
            )
        elif name == "phase_saving":
            detail = payload.get("message") or "UKLÁDÁM"
            if "EXPORT" in str(detail).upper():
                progress_txt = "UKLÁDÁM (TAR)"
            else:
                progress_txt = "UKLÁDÁM"
            self._set_capture_step(
                AppState.SAVING,
                step=7,
                label="SAVING",
                progress=progress_txt,
                message="UKLÁDÁM",
            )
        elif name == "capture_result":
            self._show_capture_result(payload)
            log_event(self.logger, "capture_result", **payload)
        elif name == "collector_finished":
            # Worker ended; keep result screen if already shown.
            if self.state.get().state in FIELD_CAPTURE_STATES:
                # Aborted/stopped without capture_result.
                if self.state.get().state == AppState.STOPPING:
                    self.state.set_state(
                        AppState.READY if self._selected_port else AppState.READER_MISSING
                    )
            log_event(self.logger, "collector_finished", **payload)
        elif name == "loop_error":
            log_event(self.logger, name, **payload)
        elif name == "collector_fatal":
            self.state.set_state(
                AppState.FAILURE,
                message="SELHALO",
                progress=str(payload.get("error") or "READER ERROR")[:40],
                banner="error",
                capture_outcome="failed",
                capture_step=7,
                capture_step_total=7,
                capture_step_label="DONE",
            )
            self.state.update(error_count=self.state.get().error_count + 1)
            log_event(self.logger, name, **payload)
        elif name == "collector_stopped":
            if self.state.get().state == AppState.STOPPING:
                self.state.set_state(
                    AppState.READY if self._selected_port else AppState.READER_MISSING
                )

    def pump(self) -> None:
        # Bound work per frame so a busy collector cannot stall the UI thread.
        for _ in range(64):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event.name, event.payload)

        # One-shot: never auto-advance from result to "next tag".
        if self._banner_until and time.monotonic() >= self._banner_until:
            self._banner_until = 0.0
            if self.state.get().state not in FIELD_RESULT_STATES | SWEETP_STATES:
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
        try:
            self.ui.start()
        except Exception as exc:  # noqa: BLE001 - must surface display failures
            log_event(self.logger, "ui_start_failed", error=str(exc))
            self.logger.exception("UI failed to start: %s", exc)
            self.state.set_state(AppState.FATAL_ERROR, message="UI START FAILED")
            # Non-zero so systemd Restart=on-failure can retry after display is ready.
            return 1
        try:
            self.initialize()
            log_event(
                self.logger,
                "boot",
                config_keys=list(self.config.keys()),
                video_driver=getattr(self.ui, "video_driver", None),
            )
            while self._running:
                self.pump()
                time.sleep(0.03)
        finally:
            self.close()
            self.state.set_state(AppState.STOPPED)
        return 0
