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
    SWEETP_STARTING = "SWEETP_STARTING"
    SWEETP_WAITING_FOR_TAG = "SWEETP_WAITING_FOR_TAG"
    SWEETP_CHECKING = "SWEETP_CHECKING"
    SWEETP_GOOD_POSITION = "SWEETP_GOOD_POSITION"
    SWEETP_UNSTABLE_POSITION = "SWEETP_UNSTABLE_POSITION"
    SWEETP_READER_ERROR = "SWEETP_READER_ERROR"
    SWEETP_CANCELLED = "SWEETP_CANCELLED"


USER_TEXT = {
    AppState.BOOTING: "Booting…",
    AppState.INITIALIZING: "Initializing…",
    AppState.READER_SEARCH: "Looking for reader…",
    AppState.READER_MISSING: "READER NOT FOUND",
    AppState.MULTIPLE_READERS: "MULTIPLE READERS",
    AppState.READY: "READY",
    AppState.STARTING: "SNIFFING…",
    AppState.WAITING_FOR_TAG: "SNIFFING ACTIVE",
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
    AppState.SWEETP_STARTING: "SWEETP",
    AppState.SWEETP_WAITING_FOR_TAG: "SWEETP",
    AppState.SWEETP_CHECKING: "TAG DETECTED",
    AppState.SWEETP_GOOD_POSITION: "POSITION OK",
    AppState.SWEETP_UNSTABLE_POSITION: "MOVE READER",
    AppState.SWEETP_READER_ERROR: "SWEETP READER ERROR",
    AppState.SWEETP_CANCELLED: "SWEETP CANCELLED",
}

SWEETP_STATES = {
    AppState.SWEETP_STARTING,
    AppState.SWEETP_WAITING_FOR_TAG,
    AppState.SWEETP_CHECKING,
    AppState.SWEETP_GOOD_POSITION,
    AppState.SWEETP_UNSTABLE_POSITION,
    AppState.SWEETP_READER_ERROR,
    AppState.SWEETP_CANCELLED,
}

FIELD_ACTIVE_STATES = {
    AppState.STARTING,
    AppState.WAITING_FOR_TAG,
    AppState.TAG_DETECTED,
    AppState.READING_IDENTIFICATION,
    AppState.READING_EEPROM,
    AppState.READING_APPLICATION,
    AppState.READING_SESSION,
    AppState.VERIFYING,
    AppState.SAVING,
    AppState.SUCCESS,
    AppState.WARNING,
    AppState.FAILURE,
    AppState.WAITING_FOR_REMOVAL,
    AppState.STOPPING,
}


# Ordered capture steps shown in the sniffing progress UI.
CAPTURE_STEPS = (
    "WAITING",
    "IDENTIFICATION",
    "APPLICATION",
    "SESSION",
    "VERIFYING",
    "SAVING",
    "DONE",
)


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
    sweetp_quality: str = ""
    sweetp_attempt: int = 0
    sweetp_total: int = 0
    sweetp_successes: int = 0
    capture_step: int = 0
    capture_step_total: int = 6
    capture_step_label: str = ""


@dataclass
class AppEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
