from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonlHandler(logging.Handler):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.now(timezone.utc).isoformat(),
        }
        extra = getattr(record, "event", None)
        if isinstance(extra, dict):
            payload["event"] = extra
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def setup_logging(log_root: Path) -> logging.Logger:
    log_root = Path(log_root)
    log_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hwsniff")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    text_path = log_root / "hwsniff.log"
    handler = RotatingFileHandler(
        text_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.addHandler(JsonlHandler(log_root / "collector.jsonl"))
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, name: str, **payload: Any) -> None:
    logger.info("%s %s", name, payload, extra={"event": {"name": name, **payload}})
