"""Persistent upload manifest (atomic JSON)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class BundleStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"


@dataclass
class BundleRecord:
    local_path: str
    remote_name: str
    size: int
    mtime: float
    sha256: str
    status: BundleStatus = BundleStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    uploaded_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleRecord:
        status_raw = data.get("status", BundleStatus.PENDING.value)
        try:
            status = BundleStatus(status_raw)
        except ValueError:
            status = BundleStatus.PENDING
        return cls(
            local_path=str(data.get("local_path") or ""),
            remote_name=str(data.get("remote_name") or ""),
            size=int(data.get("size") or 0),
            mtime=float(data.get("mtime") or 0.0),
            sha256=str(data.get("sha256") or ""),
            status=status,
            attempts=int(data.get("attempts") or 0),
            last_error=_sanitize_error(data.get("last_error")),
            uploaded_at=data.get("uploaded_at"),
        )


def _sanitize_error(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    # Never persist credential-looking fragments
    lowered = text.lower()
    for needle in ("password", "passwd", "pwd=", "://"):
        if needle in lowered and "@" in text:
            return "error_redacted"
    return text[:500]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class UploadStateStore:
    path: Path
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    records: dict[str, BundleRecord] = field(default_factory=dict)

    def load(self) -> None:
        with self._lock:
            path = Path(self.path)
            if not path.exists():
                self.records = {}
                return
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                bak = path.with_name(path.name + ".corrupt")
                try:
                    shutil.copy2(path, bak)
                except OSError:
                    bak = path
                log.error(
                    "upload state corrupt — backup=%s error=%s; rebuilding pending index",
                    bak,
                    type(exc).__name__,
                )
                self.records = {}
                return

            items = raw.get("bundles") if isinstance(raw, dict) else None
            if not isinstance(items, list):
                log.error("upload state missing bundles list — rebuilding")
                self.records = {}
                return

            records: dict[str, BundleRecord] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                rec = BundleRecord.from_dict(item)
                if not rec.local_path:
                    continue
                # Interrupted transfer after reboot
                if rec.status == BundleStatus.UPLOADING:
                    rec.status = BundleStatus.PENDING
                    rec.last_error = rec.last_error or "interrupted_upload"
                key = self._key(rec)
                records[key] = rec
            self.records = records

    def save(self) -> None:
        with self._lock:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "bundles": [r.to_dict() for r in self.records.values()],
            }
            tmp = path.with_name(path.name + ".tmp")
            data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)

    @staticmethod
    def _key(rec: BundleRecord) -> str:
        return f"{rec.local_path}|{rec.sha256}|{rec.size}"

    def get_by_path(self, local_path: str) -> list[BundleRecord]:
        with self._lock:
            return [r for r in self.records.values() if r.local_path == local_path]

    def upsert(self, rec: BundleRecord) -> BundleRecord:
        with self._lock:
            key = self._key(rec)
            # Drop older identity for same path+hash collision
            self.records[key] = rec
            return rec

    def mark_uploaded(self, rec: BundleRecord) -> None:
        with self._lock:
            rec.status = BundleStatus.UPLOADED
            rec.uploaded_at = _utc_now_iso()
            rec.last_error = None
            self.records[self._key(rec)] = rec

    def mark_failed(self, rec: BundleRecord, error: str) -> None:
        with self._lock:
            rec.status = BundleStatus.FAILED
            rec.last_error = _sanitize_error(error)
            self.records[self._key(rec)] = rec

    def mark_uploading(self, rec: BundleRecord) -> None:
        with self._lock:
            rec.status = BundleStatus.UPLOADING
            rec.attempts += 1
            self.records[self._key(rec)] = rec

    def pending_or_failed(self) -> list[BundleRecord]:
        with self._lock:
            return [
                r
                for r in self.records.values()
                if r.status in (BundleStatus.PENDING, BundleStatus.FAILED)
            ]

    def counts(self) -> dict[str, int]:
        with self._lock:
            out = {s.value: 0 for s in BundleStatus}
            for r in self.records.values():
                out[r.status.value] = out.get(r.status.value, 0) + 1
            return out

    def find_uploaded_match(
        self, *, local_path: str, size: int, sha256: str
    ) -> BundleRecord | None:
        with self._lock:
            for r in self.records.values():
                if (
                    r.local_path == local_path
                    and r.size == size
                    and r.sha256 == sha256
                    and r.status == BundleStatus.UPLOADED
                ):
                    return r
        return None
