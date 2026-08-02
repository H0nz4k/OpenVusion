from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable


_KNOWN_CMDS: dict[bytes, str] = {
    b"\x00\x04": "GetVersionString",
    b"\x00\x06": "GetDeviceType",
    b"\x05\x00": "SearchTag",
    b"\x05\x01": "SetRFOff",
    b"\x05\x02": "SetTagTypes",
    b"\x05\x03": "GetTagTypes",
    b"\x05\x04": "GetSupportedTagTypes",
    b"\x12\x07": "ISO14443_3_TDX",
}


def decode_command(command: bytes) -> str | None:
    if len(command) < 2:
        return None
    return _KNOWN_CMDS.get(command[:2])


class RawSerialTracer:
    """Append-only JSONL wire tracer for Simple Protocol exchanges.

    I/O failures never propagate into the reader exchange path.
    """

    def __init__(
        self,
        path: Path,
        *,
        on_error: Callable[[str, BaseException], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._on_error = on_error
        self._t0 = time.monotonic()
        self.enabled = True
        self.closed = False
        self.io_errors: list[str] = []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
        except OSError as exc:
            self._disable(exc)

    def close(self) -> None:
        """Mark tracer closed; further writes are no-ops."""
        self.closed = True
        self.enabled = False

    def _disable(self, exc: BaseException) -> None:
        msg = f"{type(exc).__name__}: {exc}"
        self.io_errors.append(msg)
        self.enabled = False
        if self._on_error is not None:
            try:
                self._on_error(msg, exc)
            except Exception:  # noqa: BLE001
                pass

    def _append(self, record: dict[str, Any]) -> None:
        if not self.enabled or self.closed:
            return
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self._disable(exc)

    def log_tx(self, command: bytes) -> float:
        now = time.monotonic()
        if not self.enabled or self.closed:
            return now
        decoded = decode_command(command)
        rec: dict[str, Any] = {
            "direction": "TX",
            "t_mono": round(now - self._t0, 6),
            "raw_hex": command.hex(" ").upper(),
            "wire_hex": (command.hex().upper() + "0D"),
        }
        if decoded is not None:
            rec["decoded"] = decoded
        self._append(rec)
        return now

    def log_rx(
        self,
        response: bytes,
        *,
        started: float,
        error: str | None = None,
    ) -> None:
        if not self.enabled or self.closed:
            return
        now = time.monotonic()
        rec: dict[str, Any] = {
            "direction": "RX",
            "t_mono": round(now - self._t0, 6),
            "latency_ms": round((now - started) * 1000.0, 2),
            "raw_hex": response.hex(" ").upper() if response else "",
            "length": len(response) if response else 0,
        }
        if error is not None:
            rec["error"] = error
        self._append(rec)

    def log_timeout(self, command: bytes, *, started: float, error: str) -> None:
        """Log a real reader/transport failure (not a diagnostic I/O error)."""
        if not self.enabled or self.closed:
            return
        now = time.monotonic()
        decoded = decode_command(command)
        rec: dict[str, Any] = {
            "direction": "TIMEOUT",
            "t_mono": round(now - self._t0, 6),
            "latency_ms": round((now - started) * 1000.0, 2),
            "raw_hex": command.hex(" ").upper(),
            "error": error,
        }
        if decoded is not None:
            rec["decoded"] = decoded
        self._append(rec)

    def wrap_exchange(
        self, exchange: Callable[[bytes], bytes]
    ) -> Callable[[bytes], bytes]:
        def traced(command: bytes) -> bytes:
            started = time.monotonic()
            # Diagnostic TX log — never blocks the reader command.
            try:
                started = self.log_tx(command)
            except Exception as exc:  # noqa: BLE001
                self._disable(exc)

            try:
                response = exchange(command)
            except Exception as exc:  # noqa: BLE001
                try:
                    self.log_timeout(command, started=started, error=str(exc))
                except Exception as log_exc:  # noqa: BLE001
                    self._disable(log_exc)
                raise

            try:
                self.log_rx(response, started=started)
            except Exception as exc:  # noqa: BLE001
                self._disable(exc)
            return response

        return traced
