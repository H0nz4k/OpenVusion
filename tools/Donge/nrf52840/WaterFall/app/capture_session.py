from __future__ import annotations

import json
import shutil
import threading
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionInfo:
    session_id: str
    label: str
    notes: str
    started_at: str
    stopped_at: str = ""
    directory: str = ""
    zip_file: str = ""


class CaptureSession:
    """Thread-safe multi-source capture bundle writer."""

    def __init__(self, root: str, version: str, config_snapshot: dict) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.version = version
        self.config_snapshot = config_snapshot
        self.lock = threading.Lock()
        self.info: SessionInfo | None = None
        self.files: dict[str, Any] = {}
        self.device_snapshot_provider = None

    @property
    def active(self) -> bool:
        return self.info is not None and not self.info.stopped_at

    def set_device_snapshot_provider(self, provider) -> None:
        self.device_snapshot_provider = provider

    def start(self, label: str = "", notes: str = "") -> SessionInfo:
        with self.lock:
            if self.active:
                return self.info
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            sid = f"waterfall_{stamp}"
            directory = self.root / sid
            directory.mkdir(parents=True, exist_ok=False)
            self.info = SessionInfo(
                session_id=sid,
                label=label.strip(),
                notes=notes.strip(),
                started_at=datetime.now().isoformat(timespec="milliseconds"),
                directory=str(directory),
            )
            (directory / "config_snapshot.json").write_text(
                json.dumps(self.config_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.files = {
                "sweeps": (directory / "rf_sweeps.jsonl").open("a", encoding="utf-8"),
                "rf_events": (directory / "rf_events.jsonl").open("a", encoding="utf-8"),
                "packets": (directory / "packets.jsonl").open("a", encoding="utf-8"),
                "markers": (directory / "markers.jsonl").open("a", encoding="utf-8"),
                "watch": (directory / "watch_rssi.jsonl").open("a", encoding="utf-8"),
            }
            self._write_metadata_locked()
            return self.info

    def _write_metadata_locked(self) -> None:
        if not self.info:
            return
        directory = Path(self.info.directory)
        payload = {
            **asdict(self.info),
            "waterfall_version": self.version,
            "format": "OpenVusion WaterFall capture bundle v1",
            "files": [
                "rf_sweeps.jsonl",
                "rf_events.jsonl",
                "packets.jsonl",
                "markers.jsonl",
                "watch_rssi.jsonl",
                "devices.json",
                "config_snapshot.json",
            ],
        }
        (directory / "metadata.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def write(self, stream: str, payload: dict) -> None:
        with self.lock:
            if not self.active:
                return
            fp = self.files.get(stream)
            if fp:
                fp.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                fp.flush()

    def stop(self) -> SessionInfo | None:
        with self.lock:
            if not self.info:
                return None
            if self.info.stopped_at:
                return self.info
            self.info.stopped_at = datetime.now().isoformat(timespec="milliseconds")
            for fp in self.files.values():
                try:
                    fp.flush()
                    fp.close()
                except Exception:
                    pass
            self.files = {}

            directory = Path(self.info.directory)
            devices = self.device_snapshot_provider() if self.device_snapshot_provider else []
            (directory / "devices.json").write_text(
                json.dumps(devices, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            zip_path = self.root / f"{self.info.session_id}.zip"
            self.info.zip_file = str(zip_path)
            self._write_metadata_locked()
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(directory.iterdir()):
                    if p.is_file():
                        zf.write(p, arcname=p.name)
            return self.info

    def latest_zip(self) -> Path | None:
        with self.lock:
            if self.info and self.info.zip_file:
                p = Path(self.info.zip_file)
                if p.exists():
                    return p
        zips = sorted(self.root.glob("waterfall_*.zip"), reverse=True)
        return zips[0] if zips else None

    def list_sessions(self) -> list[dict]:
        """List recorded session directories and ZIP bundles, newest first."""
        rows: list[dict] = []
        for directory in sorted(
            (p for p in self.root.glob("waterfall_*") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            meta_path = directory / "metadata.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            except Exception:
                meta = {}
            zip_path = self.root / f"{directory.name}.zip"
            rows.append({
                "session_id": directory.name,
                "label": meta.get("label", ""),
                "notes": meta.get("notes", ""),
                "started_at": meta.get("started_at", ""),
                "stopped_at": meta.get("stopped_at", ""),
                "active": bool(self.info and self.active and self.info.session_id == directory.name),
                "zip_ready": zip_path.exists(),
                "zip_size": zip_path.stat().st_size if zip_path.exists() else 0,
            })
        return rows

    def _session_dir(self, session_id: str) -> Path:
        if not session_id.startswith("waterfall_") or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in session_id):
            raise ValueError("Neplatné session_id")
        path = (self.root / session_id).resolve()
        root = self.root.resolve()
        if root not in path.parents or not path.is_dir():
            raise FileNotFoundError(session_id)
        return path

    def read_stream(self, session_id: str, stream: str, limit: int = 1000) -> list[dict]:
        mapping = {
            "sweeps": "rf_sweeps.jsonl",
            "rf_events": "rf_events.jsonl",
            "packets": "packets.jsonl",
            "markers": "markers.jsonl",
            "watch": "watch_rssi.jsonl",
        }
        if stream not in mapping:
            raise ValueError("Neznámý stream")
        path = self._session_dir(session_id) / mapping[stream]
        if not path.exists():
            return []
        limit = max(1, min(int(limit), 10000))
        # Session files are intentionally line-oriented. Keep only the tail so
        # browsing a long field capture cannot exhaust Pi 3 RAM.
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({"parse_error": True, "raw": line})
        return out
