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
    CAPTURE_DETAIL = "CAPTURE_DETAIL"
    WAITING_FOR_REMOVAL = "WAITING_FOR_REMOVAL"  # legacy; unused by one-shot START
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
    AppState.SUCCESS: "HOTOVO",
    AppState.WARNING: "HOTOVO S CHYBAMI",
    AppState.FAILURE: "SELHALO",
    AppState.CAPTURE_DETAIL: "DETAIL ZÁZNAMU",
    AppState.WAITING_FOR_REMOVAL: "Oddalte štítek",
    AppState.STOPPING: "Stopping…",
    AppState.STOPPED: "STOPPED",
    AppState.STORAGE_ERROR: "STORAGE FULL / ERROR",
    AppState.READER_DISCONNECTED: "READER DISCONNECTED",
    AppState.FATAL_ERROR: "FATAL ERROR",
    AppState.SHUTDOWN_CONFIRM: "Opravdu vypnout?",
    AppState.SWEETP_STARTING: "SWEETP",
    AppState.SWEETP_WAITING_FOR_TAG: "SWEETP LIVE",
    AppState.SWEETP_CHECKING: "SWEETP LIVE",
    AppState.SWEETP_GOOD_POSITION: "POSITION OK",
    AppState.SWEETP_UNSTABLE_POSITION: "SWEETP LIVE",
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

FIELD_CAPTURE_STATES = {
    AppState.STARTING,
    AppState.WAITING_FOR_TAG,
    AppState.TAG_DETECTED,
    AppState.READING_IDENTIFICATION,
    AppState.READING_EEPROM,
    AppState.READING_APPLICATION,
    AppState.READING_SESSION,
    AppState.VERIFYING,
    AppState.SAVING,
    AppState.STOPPING,
}

FIELD_RESULT_STATES = {
    AppState.SUCCESS,
    AppState.WARNING,
    AppState.FAILURE,
    AppState.CAPTURE_DETAIL,
}

FIELD_ACTIVE_STATES = FIELD_CAPTURE_STATES | FIELD_RESULT_STATES | {
    AppState.WAITING_FOR_REMOVAL,
}


# Ordered capture steps shown in the sniffing progress UI.
CAPTURE_STEPS = (
    "WAITING",
    "IDENTIFICATION",
    "EEPROM",
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
    capture_step_total: int = 7
    capture_step_label: str = ""
    capture_directory: str = ""
    capture_export_bundle: str = ""
    capture_outcome: str = ""  # ok | with_errors | failed | duplicate | aborted
    capture_phase_errors: int = 0
    phase_identification: str = ""
    phase_eeprom: str = ""
    phase_application: str = ""
    phase_session: str = ""
    phase_verify: str = ""
    phase_save: str = ""
    # Live SweetP meter (communication quality, not RF RSSI).
    sweetp_current_quality: float = 0.0
    sweetp_best_quality: float = 0.0
    sweetp_trend: str = "stable"  # improving | worsening | stable
    sweetp_window_successes: int = 0
    sweetp_window_total: int = 0
    sweetp_total_successes: int = 0
    sweetp_total_failures: int = 0
    sweetp_dominant_uid: str = ""
    sweetp_uid_consistency: float = 0.0
    sweetp_average_latency_ms: float | None = None
    sweetp_stable_duration_ms: int = 0
    sweetp_enough_samples: bool = False
    sweetp_position_ok: bool = False
    sweetp_latency_available: bool = False


@dataclass
class AppEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
