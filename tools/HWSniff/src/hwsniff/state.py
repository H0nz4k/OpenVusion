from __future__ import annotations

import threading
from typing import Callable

from .models import USER_TEXT, AppState, UiSnapshot


class AppStateMachine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.snapshot = UiSnapshot()
        self._listeners: list[Callable[[UiSnapshot], None]] = []

    def subscribe(self, callback: Callable[[UiSnapshot], None]) -> None:
        self._listeners.append(callback)

    def get(self) -> UiSnapshot:
        with self._lock:
            return UiSnapshot(**self.snapshot.__dict__)

    def update(self, **kwargs) -> UiSnapshot:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self.snapshot, key, value)
            if "state" in kwargs and "message" not in kwargs:
                self.snapshot.message = USER_TEXT.get(kwargs["state"], "")
            snap = UiSnapshot(**self.snapshot.__dict__)
        for listener in self._listeners:
            listener(snap)
        return snap

    def set_state(self, state: AppState, **kwargs) -> UiSnapshot:
        return self.update(state=state, **kwargs)

    def allowed_actions(self) -> set[str]:
        state = self.get().state
        mapping = {
            AppState.READY: {"start", "sweetp", "shutdown"},
            AppState.READER_MISSING: {"retry"},
            AppState.MULTIPLE_READERS: {"select", "retry"},
            AppState.WAITING_FOR_TAG: {"stop"},
            AppState.TAG_DETECTED: {"stop"},
            AppState.READING_IDENTIFICATION: {"stop"},
            AppState.READING_EEPROM: {"stop"},
            AppState.READING_APPLICATION: {"stop"},
            AppState.READING_SESSION: {"stop"},
            AppState.VERIFYING: {"stop"},
            AppState.SAVING: {"stop"},
            AppState.SUCCESS: {"new_tag", "detail", "back"},
            AppState.FAILURE: {"new_tag", "detail", "back"},
            AppState.WARNING: {"new_tag", "detail", "back"},
            AppState.CAPTURE_DETAIL: {"new_tag", "back"},
            AppState.WAITING_FOR_REMOVAL: {"stop"},
            AppState.READER_DISCONNECTED: {"retry"},
            AppState.STORAGE_ERROR: {"retry"},
            AppState.SHUTDOWN_CONFIRM: {"shutdown_cancel", "shutdown_confirm"},
            AppState.SWEETP_STARTING: {"sweetp_cancel"},
            AppState.SWEETP_WAITING_FOR_TAG: {"sweetp_cancel"},
            AppState.SWEETP_CHECKING: {"sweetp_cancel", "sweetp_done"},
            AppState.SWEETP_GOOD_POSITION: {"sweetp_cancel", "sweetp_done"},
            AppState.SWEETP_UNSTABLE_POSITION: {"sweetp_cancel", "sweetp_done"},
            AppState.SWEETP_READER_ERROR: {"sweetp_cancel", "sweetp_retry"},
            AppState.SWEETP_CANCELLED: {"sweetp_done"},
        }
        return mapping.get(state, set())
