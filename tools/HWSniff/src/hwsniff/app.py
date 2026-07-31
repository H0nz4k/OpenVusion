from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any, Callable

from elatec_uid_tool.field_collector import CapturePhase, FinishStatus

from .collector_service import CollectorService
from .configuration import load_config
from .logging_setup import log_event, setup_logging
from .models import AppState, UiSnapshot
from .reader_detection import scan_readers, select_reader
from .state import AppStateMachine
from .storage import prepare_storage, storage_status
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
        self._list_ports = list_ports
        self._client_factory = client_factory
        self._selected_port: str | None = None
        self._candidates = []
        self._banner_until = 0.0
        self._running = False

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
        self.state.set_state(
            AppState.READY,
            reader_label=f"READER READY: {chosen.device}",
            candidates=[],
        )

    def start_collection(self) -> None:
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
        self.state.set_state(AppState.STARTING)
        self.collector.start(self._selected_port, self.config)
        self.state.set_state(AppState.WAITING_FOR_TAG, progress="")
        log_event(self.logger, "start", port=self._selected_port)

    def stop_collection(self) -> None:
        self.state.set_state(AppState.STOPPING)
        self.collector.stop()
        self.state.set_state(AppState.READY if self._selected_port else AppState.READER_MISSING)
        log_event(self.logger, "stop")

    def handle_action(self, action: UiAction) -> None:
        name = action.name
        if name == "start":
            self.start_collection()
        elif name == "stop":
            self.stop_collection()
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
            self.state.set_state(AppState.SHUTDOWN_CONFIRM)
        elif name == "shutdown_cancel":
            self.state.set_state(AppState.READY)
        elif name == "shutdown_confirm":
            log_event(self.logger, "shutdown")
            request_shutdown()
        elif name == "quit":
            self._running = False

    def handle_event(self, name: str, payload: dict[str, Any]) -> None:
        if name == "tag_detected":
            self.state.set_state(
                AppState.TAG_DETECTED,
                last_uid=payload.get("uid") or "—",
                progress="TAG DETECTED",
            )
        elif name == "phase_identification":
            self.state.set_state(
                AppState.READING_IDENTIFICATION, progress=payload.get("message", "")
            )
        elif name == "phase_eeprom":
            self.state.set_state(AppState.READING_EEPROM, progress=payload.get("message", ""))
        elif name == "phase_application":
            self.state.set_state(
                AppState.READING_APPLICATION, progress=payload.get("message", "")
            )
        elif name == "phase_session":
            self.state.set_state(AppState.READING_SESSION, progress=payload.get("message", ""))
        elif name == "phase_verifying":
            self.state.set_state(AppState.VERIFYING, progress="VERIFYING")
        elif name == "phase_saving":
            self.state.set_state(AppState.SAVING, progress="SAVING")
        elif name == "capture_result":
            snap = self.state.get()
            if payload.get("ok"):
                self.state.update(
                    ok_count=snap.ok_count + 1,
                    last_uid=payload.get("uid") or snap.last_uid,
                    banner="ok",
                )
                self.state.set_state(
                    AppState.SUCCESS,
                    message=f"CAPTURE OK\nUID: {payload.get('uid')}",
                    progress="",
                )
                self._banner_until = time.monotonic() + float(
                    (self.config.get("ui") or {}).get("success_display_seconds", 1.5)
                )
            else:
                self.state.update(error_count=snap.error_count + 1, banner="error")
                err = "; ".join(payload.get("errors") or ["unknown"])
                self.state.set_state(
                    AppState.FAILURE,
                    message=f"CAPTURE INCOMPLETE\n{err[:40]}",
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
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event.name, event.payload)

        if self._banner_until and time.monotonic() >= self._banner_until:
            self._banner_until = 0.0
            if self.collector.running:
                self.state.update(banner=None)
                self.state.set_state(AppState.WAITING_FOR_TAG, progress="")
            else:
                self.state.update(banner=None)

        for action in self.ui.poll_actions():
            self.handle_action(action)
        self.ui.draw(self.state.get())

    def close(self) -> None:
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
