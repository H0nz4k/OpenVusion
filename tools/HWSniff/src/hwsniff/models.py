from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AppState(str, Enum):
    BOOTING = "BOOTING"
    INITIALIZING = "INITIALIZING"
    READER_SEARCH = "READER_SEARCH"
    READER_MISSING = "READER_MISSING"
    MULTIPLE_READERS = "MULTIPLE_READERS"
    READY = "READY"
    STARTING = "STARTING"
    WAITING_FOR_TAG = "WAITING_FOR_TAG"
    TAG_DETECTED = "TAG_DETECTED"
    READING_IDENTIFICATION = "READING_IDENTIFICATION"
    READING_EEPROM = "READING_EEPROM"
    READING_APPLICATION = "READING_APPLICATION"
    READING_SESSION = "READING_SESSION"
    VERIFYING = "VERIFYING"
    SAVING = "SAVING"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILURE = "FAILURE"
    WAITING_FOR_REMOVAL = "WAITING_FOR_REMOVAL"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    STORAGE_ERROR = "STORAGE_ERROR"
    READER_DISCONNECTED = "READER_DISCONNECTED"
    FATAL_ERROR = "FATAL_ERROR"
    SHUTDOWN_CONFIRM = "SHUTDOWN_CONFIRM"


USER_TEXT = {
    AppState.BOOTING: "Booting…",
    AppState.INITIALIZING: "Initializing…",
    AppState.READER_SEARCH: "Looking for reader…",
    AppState.READER_MISSING: "READER NOT FOUND",
    AppState.MULTIPLE_READERS: "MULTIPLE READERS",
    AppState.READY: "READY",
    AppState.STARTING: "Starting…",
    AppState.WAITING_FOR_TAG: "Přiložte štítek",
    AppState.TAG_DETECTED: "TAG DETECTED",
    AppState.READING_IDENTIFICATION: "IDENTIFICATION",
    AppState.READING_EEPROM: "EEPROM",
    AppState.READING_APPLICATION: "APPLICATION BLOCK",
    AppState.READING_SESSION: "SESSION",
    AppState.VERIFYING: "VERIFYING",
    AppState.SAVING: "SAVING",
    AppState.SUCCESS: "CAPTURE OK",
    AppState.WARNING: "CAPTURE WARNING",
    AppState.FAILURE: "CAPTURE INCOMPLETE",
    AppState.WAITING_FOR_REMOVAL: "Oddalte štítek",
    AppState.STOPPING: "Stopping…",
    AppState.STOPPED: "STOPPED",
    AppState.STORAGE_ERROR: "STORAGE FULL / ERROR",
    AppState.READER_DISCONNECTED: "READER DISCONNECTED",
    AppState.FATAL_ERROR: "FATAL ERROR",
    AppState.SHUTDOWN_CONFIRM: "Opravdu vypnout?",
}


@dataclass
class UiSnapshot:
    state: AppState = AppState.BOOTING
    reader_label: str = ""
    storage_text: str = ""
    last_uid: str = "—"
    ok_count: int = 0
    error_count: int = 0
    progress: str = ""
    message: str = ""
    candidates: list[str] = field(default_factory=list)
    banner: str | None = None  # "ok" | "error" | None


@dataclass
class AppEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
