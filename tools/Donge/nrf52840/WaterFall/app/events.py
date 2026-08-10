from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Marker:
    host_time: str
    kind: str
    label: str
    source: str
    data: dict[str, Any]


class EventRecorder:
    """Thread-safe JSONL recorder for experiment markers."""

    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fp = None
        self.path: Path | None = None

    def start(self) -> str:
        with self._lock:
            if self._fp:
                return str(self.path)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = self.directory / f"experiment_{stamp}.jsonl"
            self._fp = self.path.open("a", encoding="utf-8")
            return str(self.path)

    def stop(self) -> None:
        with self._lock:
            if self._fp:
                self._fp.flush()
                self._fp.close()
            self._fp = None

    def emit(self, kind: str, label: str, source: str, **data) -> Marker:
        marker = Marker(
            host_time=datetime.now().isoformat(timespec="milliseconds"),
            kind=kind,
            label=label,
            source=source,
            data=data,
        )
        with self._lock:
            if self._fp:
                self._fp.write(json.dumps(asdict(marker), ensure_ascii=False) + "\n")
                self._fp.flush()
        return marker
