"""Adapt ProbeResult ↔ FieldCollector / HWSniff contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..field_collector.models import FieldCaptureResult, FinishStatus
from .capture import ProbeResult
from .status import OverallStatus, PhaseStatus


def _ui_phase(status: str | None) -> str:
    if not status:
        return "pending"
    if status in (PhaseStatus.OK.value,):
        return "ok"
    if status in (PhaseStatus.SKIPPED.value, PhaseStatus.UNSUPPORTED.value):
        return "skipped"
    if status == PhaseStatus.PENDING.value:
        return "pending"
    return "error"


def probe_phase_status_for_ui(phase_statuses: dict[str, str]) -> dict[str, str]:
    """Map engine phase keys to HWSniff detail keys."""
    return {
        "identification": _ui_phase(phase_statuses.get("identification")),
        "eeprom": _ui_phase(phase_statuses.get("eeprom")),
        "application": _ui_phase(phase_statuses.get("application")),
        "session": _ui_phase(phase_statuses.get("session")),
        "verify": _ui_phase(phase_statuses.get("verification")),
        "save": (
            "ok"
            if phase_statuses
            and any(
                phase_statuses.get(k) == PhaseStatus.OK.value
                for k in (
                    "identification",
                    "application",
                    "eeprom",
                    "tag_detection",
                )
            )
            else _ui_phase(phase_statuses.get("reader_info"))
        ),
    }


def probe_to_field_result(
    result: ProbeResult,
    *,
    export_bundle: str | None = None,
) -> FieldCaptureResult:
    """Convert shared-engine result to FieldCaptureResult for HWSniff UI."""
    errors = [
        f"{e.get('phase', '?')}: {e.get('message', e)}"
        if isinstance(e, dict)
        else str(e)
        for e in result.errors
    ]
    phase_status = probe_phase_status_for_ui(result.phase_statuses)

    if result.duplicate:
        finish = FinishStatus.DUPLICATE_SKIPPED
    elif result.aborted and not result.uid:
        finish = FinishStatus.ABORTED
    elif result.overall == OverallStatus.SUCCESS:
        finish = FinishStatus.COMPLETED_SUCCESSFULLY
    elif result.overall == OverallStatus.PARTIAL:
        finish = FinishStatus.COMPLETED_WITH_ERRORS
    else:
        finish = FinishStatus.PARTIAL

    get_version = None
    app_hex = None
    # Best-effort extract from phase files is left to callers; metadata carries paths.
    metadata: dict[str, Any] = {
        "engine": "readonly_capture",
        "overall_status": result.overall.value,
        "phase_statuses": dict(result.phase_statuses),
        "phase_status": phase_status,
        "output_dir": str(result.output_dir),
    }
    if export_bundle:
        metadata["export_bundle"] = export_bundle

    # Pull identification / application hex from summary if present.
    summary_path = Path(result.output_dir) / "summary.json"
    if summary_path.exists():
        try:
            import json

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            ident = summary.get("identification") or {}
            get_version = ident.get("raw_hex")
            metadata["summary"] = {
                "uid": summary.get("uid"),
                "overall_status": summary.get("overall_status"),
            }
        except (OSError, ValueError):
            pass

    app_path = Path(result.output_dir) / "phases" / "application.json"
    if app_path.exists():
        try:
            import json

            app = json.loads(app_path.read_text(encoding="utf-8"))
            app_hex = app.get("raw_hex")
        except (OSError, ValueError):
            pass

    directory = str(result.output_dir) if result.output_dir else None
    return FieldCaptureResult(
        uid=result.uid,
        get_version=get_version,
        directory=directory,
        finish_status=finish,
        application_block_hex=app_hex,
        errors=errors,
        duplicate=result.duplicate,
        metadata=metadata,
        phase_status=phase_status,
    )
