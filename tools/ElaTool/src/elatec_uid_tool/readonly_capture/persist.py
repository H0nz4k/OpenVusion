from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


@dataclass
class CaptureStore:
    """Immediate-on-disk persistence for one capture run.

    The working directory stays stable for the whole capture. Rename to the
    final ``UID-<uid>`` name only via :meth:`finalize_rename` after the serial
    client and raw tracer are closed.
    """

    root: Path
    started_at: str = field(default_factory=_utc_now)
    files: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    phase_statuses: dict[str, str] = field(default_factory=dict)
    phase_attempts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    summary_extra: dict[str, Any] = field(default_factory=dict)
    _console_lines: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "phases").mkdir(exist_ok=True)
        self._touch("events.jsonl")
        errors_path = self.root / "errors.json"
        if not errors_path.exists():
            _json_dump(errors_path, [])
        self._track(errors_path)
        self.write_environment()
        self.update_summary(output_dir=str(self.root))
        self.flush_summary()

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _track(self, path: Path) -> None:
        rel = self._rel(path)
        if rel not in self.files:
            self.files.append(rel)

    def _touch(self, name: str) -> Path:
        path = self.root / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
        self._track(path)
        return path

    def log_console(self, line: str) -> None:
        self._console_lines.append(line)
        path = self.root / "console.log"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._track(path)
        except OSError as exc:
            self.add_error(
                phase="persistence",
                code="persistence_error",
                message=f"console.log write failed: {exc}",
            )

    def append_event(self, name: str, **payload: Any) -> None:
        path = self.root / "events.jsonl"
        rec = {"ts": _utc_now(), "t_mono": time.monotonic(), "event": name, **payload}
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._track(path)
        except OSError:
            # Avoid recursive error loops during persistence failure.
            pass

    def write_phase(self, name: str, data: dict[str, Any], status: str) -> Path:
        path = self.root / "phases" / f"{name}.json"
        payload = {
            "phase": name,
            "status": status,
            "updated_at": _utc_now(),
            **data,
        }
        _json_dump(path, payload)
        self._track(path)
        self.phase_statuses[name] = status
        if "attempts" in data:
            self.phase_attempts[name] = data["attempts"]
        self.flush_summary()
        self.append_event("phase_saved", phase=name, status=status)
        return path

    def add_error(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        err = {
            "ts": _utc_now(),
            "phase": phase,
            "code": code,
            "message": message,
            "details": details or {},
        }
        self.errors.append(err)
        path = self.root / "errors.json"
        try:
            _json_dump(path, self.errors)
            self._track(path)
        except OSError:
            pass
        self.append_event("error", phase=phase, code=code, message=message)
        try:
            self.flush_summary()
        except OSError:
            pass

    def write_environment(self) -> None:
        path = self.root / "environment.json"
        data = {
            "platform": platform.platform(),
            "system": platform.system(),
            "python": sys.version,
            "executable": sys.executable,
            "cwd": str(Path.cwd()),
            "machine": platform.machine(),
        }
        _json_dump(path, data)
        self._track(path)

    def update_summary(self, **kwargs: Any) -> None:
        self.summary_extra.update(kwargs)
        self.flush_summary()

    def flush_summary(self) -> None:
        path = self.root / "summary.json"
        data = {
            "started_at": self.started_at,
            "updated_at": _utc_now(),
            "ended_at": self.summary_extra.get("ended_at"),
            "com_port": self.summary_extra.get("com_port"),
            "reader": self.summary_extra.get("reader"),
            "uid": self.summary_extra.get("uid"),
            "tag_type": self.summary_extra.get("tag_type"),
            "overall_status": self.summary_extra.get("overall_status"),
            "output_dir": str(self.root),
            "phase_statuses": self.phase_statuses,
            "phase_attempts": self.phase_attempts,
            "errors": self.errors,
            "files": list(self.files),
            **{
                k: v
                for k, v in self.summary_extra.items()
                if k
                not in {
                    "ended_at",
                    "com_port",
                    "reader",
                    "uid",
                    "tag_type",
                    "overall_status",
                    "output_dir",
                }
            },
        }
        _json_dump(path, data)
        self._track(path)

    def finalize_rename(self, uid: str) -> Path:
        """Rename ``*_UID-pending`` → ``*_UID-<uid>`` after all writers are closed.

        Updates ``root``, ``output_dir`` and refreshes the file list against the
        new path. Safe no-op if already renamed or rename fails.
        """
        old = self.root
        if f"UID-{uid}" in old.name and not old.name.endswith("UID-pending"):
            self.update_summary(uid=uid, output_dir=str(old))
            return old

        if old.name.endswith("UID-pending"):
            stamp = old.name[: -len("UID-pending")].rstrip("_")
        elif "_UID-" in old.name:
            stamp = old.name.split("_UID-")[0]
        else:
            stamp = old.name

        new = old.parent / f"{stamp}_UID-{uid}"
        if new.exists():
            self.update_summary(uid=uid, output_dir=str(old))
            return old

        try:
            old.rename(new)
        except OSError as exc:
            self.add_error(
                phase="persistence",
                code="persistence_error",
                message=f"finalize rename failed: {exc}",
                details={"from": str(old), "to": str(new)},
            )
            self.update_summary(uid=uid, output_dir=str(old))
            return old

        self.root = new
        # Refresh tracked relative paths (names are unchanged under the new root).
        self.files = list(dict.fromkeys(self.files))
        self.append_event(
            "capture_dir_renamed",
            from_dir=str(old),
            to_dir=str(new),
            uid=uid,
        )
        self.update_summary(uid=uid, output_dir=str(new))
        return new

    def finalize(self, overall_status: str) -> Path:
        self.update_summary(
            ended_at=_utc_now(),
            overall_status=overall_status,
            output_dir=str(self.root),
        )
        return self.root / "summary.json"


def make_capture_dir(base: Path, uid: str | None = None) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = f"UID-{uid}" if uid else "UID-pending"
    path = Path(base) / f"{stamp}_{suffix}"
    path.mkdir(parents=True, exist_ok=True)
    return path
