from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .models import CaptureEvent


DEFAULT_CAPTURE_ROOT = Path("captures") / "logic-analyzer"


def capture_dir_name(uid: str | None, *, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    safe_uid = (uid or "unknown").replace(" ", "").upper() or "UNKNOWN"
    return f"{stamp}_{safe_uid}"


def create_capture_dir(
    output_dir: Path,
    uid: str | None,
    *,
    when: datetime | None = None,
) -> Path:
    """Vytvoří adresář capture: YYYY-MM-DD_HH-MM-SS_<UID>."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    base = capture_dir_name(uid, when=when)
    path = root / base
    suffix = 1
    while path.exists():
        path = root / f"{base}_{suffix}"
        suffix += 1
    path.mkdir(parents=True, exist_ok=False)
    return path


class CaptureWriter:
    """Průběžný zápis JSONL/CSV; bezpečně uzavírá soubory i při chybě."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

        self.timeline_path = self.directory / "timeline.jsonl"
        self.samples_path = self.directory / "samples.csv"
        self.errors_path = self.directory / "errors.jsonl"
        self.metadata_path = self.directory / "metadata.json"
        self.report_path = self.directory / "report.txt"

        self._timeline: TextIO = self.timeline_path.open(
            "w", encoding="utf-8", newline="\n"
        )
        self._errors: TextIO | None = None
        self._csv_file: TextIO = self.samples_path.open(
            "w", encoding="utf-8-sig", newline=""
        )
        self._csv = csv.DictWriter(
            self._csv_file,
            fieldnames=[
                "seq",
                "elapsed_us",
                "wall_time",
                "event_type",
                "rf_operation",
                "rf_duration_us",
                "raw_hex",
                "changed",
                "error",
            ],
        )
        self._csv.writeheader()
        self._csv_file.flush()

        self.event_count = 0
        self.error_count = 0
        self._closed = False

    def write_event(self, event: CaptureEvent) -> None:
        if self._closed:
            raise RuntimeError("CaptureWriter je už uzavřený.")

        payload = event.to_dict()
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._timeline.write(line + "\n")
        self._timeline.flush()
        self.event_count += 1

        changed = False
        if event.changes is not None:
            changed = bool(event.changes.get("changed"))

        self._csv.writerow(
            {
                "seq": event.seq,
                "elapsed_us": event.elapsed_us,
                "wall_time": event.wall_time,
                "event_type": event.event_type,
                "rf_operation": event.rf_operation or "",
                "rf_duration_us": (
                    "" if event.rf_duration_us is None else event.rf_duration_us
                ),
                "raw_hex": event.raw_hex or "",
                "changed": changed,
                "error": event.error or "",
            }
        )
        self._csv_file.flush()

        if event.error or event.event_type == "rf_error":
            self._write_error(payload)

    def _write_error(self, payload: dict[str, Any]) -> None:
        if self._errors is None:
            self._errors = self.errors_path.open(
                "w", encoding="utf-8", newline="\n"
            )
        self._errors.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        self._errors.flush()
        self.error_count += 1

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_binary(self, name: str, data: bytes) -> Path:
        path = self.directory / name
        path.write_bytes(data)
        return path

    def write_report(self, text: str) -> None:
        self.report_path.write_text(text, encoding="utf-8")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in (self._timeline, self._csv_file, self._errors):
            if handle is None:
                continue
            try:
                handle.flush()
            finally:
                handle.close()

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
