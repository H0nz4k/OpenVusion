from __future__ import annotations

from enum import Enum
from typing import Iterable


class PhaseStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"  # e.g. wait-for-tag deadline
    SERIAL_TIMEOUT = "serial_timeout"
    READER_ERROR = "reader_error"
    PROTOCOL_ERROR = "protocol_error"
    PERSISTENCE_ERROR = "persistence_error"
    RAW_TRACE_ERROR = "raw_trace_error"
    EXCEPTION = "exception"
    PENDING = "pending"
    SKIPPED = "skipped"


class OverallStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# Phases that must be ok for overall SUCCESS.
REQUIRED_PHASES = ("reader_info", "tag_detection", "uid_confirm")


def classify_exception(exc: BaseException) -> PhaseStatus:
    """Map an exception to a phase/attempt status.

    FileNotFoundError / I/O of diagnostics must never become timeout.
    """
    name = type(exc).__name__
    name_l = name.lower()
    text = str(exc)
    text_l = text.lower()

    if isinstance(exc, FileNotFoundError) or name_l == "filenotfounderror":
        if "raw_serial" in text_l or "raw_trace" in text_l:
            return PhaseStatus.RAW_TRACE_ERROR
        return PhaseStatus.PERSISTENCE_ERROR

    if isinstance(exc, IsADirectoryError):
        return PhaseStatus.PERSISTENCE_ERROR

    if isinstance(exc, OSError):
        # errno 2 = ENOENT — missing path (never a serial timeout).
        if getattr(exc, "errno", None) == 2 or "no such file" in text_l:
            if "raw_serial" in text_l:
                return PhaseStatus.RAW_TRACE_ERROR
            return PhaseStatus.PERSISTENCE_ERROR

    if "protocolerror" in name_l or name_l == "protocolerror":
        return PhaseStatus.PROTOCOL_ERROR

    # Prefer specific serial timeout wording over generic "serial" matching.
    if "timeout" in text_l or "neodpověděl" in text_l or "neodpovedel" in text_l:
        if "serialcommunicationerror" in name_l or "serial" in name_l:
            return PhaseStatus.SERIAL_TIMEOUT
        return PhaseStatus.SERIAL_TIMEOUT

    if name_l in {"serialcommunicationerror", "elatecerror"}:
        return PhaseStatus.READER_ERROR

    if "chyba komunikace" in text_l:
        return PhaseStatus.READER_ERROR

    return PhaseStatus.EXCEPTION


def aggregate_attempt_statuses(
    attempt_statuses: Iterable[str],
    *,
    success_count: int,
    required_successes: int,
) -> PhaseStatus:
    """Derive phase status from attempt outcomes without inventing TIMEOUT."""
    if success_count >= required_successes:
        return PhaseStatus.OK
    if success_count > 0:
        return PhaseStatus.PARTIAL

    statuses = [PhaseStatus(s) if not isinstance(s, PhaseStatus) else s
                for s in attempt_statuses]
    if not statuses:
        return PhaseStatus.EXCEPTION

    # Prefer the most informative failure; never promote FileNotFound to timeout.
    priority = [
        PhaseStatus.RAW_TRACE_ERROR,
        PhaseStatus.PERSISTENCE_ERROR,
        PhaseStatus.PROTOCOL_ERROR,
        PhaseStatus.READER_ERROR,
        PhaseStatus.SERIAL_TIMEOUT,
        PhaseStatus.TIMEOUT,
        PhaseStatus.EXCEPTION,
    ]
    for cand in priority:
        if any(s == cand for s in statuses):
            return cand
    return statuses[-1]


def compute_overall(
    phase_statuses: dict[str, str],
    *,
    uid: str | None,
    usable_data: bool,
) -> OverallStatus:
    """Derive SUCCESS / PARTIAL / FAILED from phase outcomes.

    SUCCESS — required phases OK and every other executed phase OK or SKIPPED.
    PARTIAL — usable data/UID present, but some phases failed/partial/unsupported.
    FAILED  — no reader/tag/usable data.
    """
    statuses = {
        k: PhaseStatus(v) if not isinstance(v, PhaseStatus) else v
        for k, v in phase_statuses.items()
    }

    if not uid and not usable_data:
        return OverallStatus.FAILED

    required_present = [p for p in REQUIRED_PHASES if p in statuses]
    required_ok = bool(required_present) and all(
        statuses[p] == PhaseStatus.OK for p in required_present
    )

    if not required_ok and not usable_data:
        return OverallStatus.FAILED

    soft_ok = {PhaseStatus.OK, PhaseStatus.SKIPPED}
    if required_ok and all(s in soft_ok for s in statuses.values()):
        return OverallStatus.SUCCESS

    if uid or usable_data:
        return OverallStatus.PARTIAL

    return OverallStatus.FAILED

