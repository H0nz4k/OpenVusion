from __future__ import annotations

import threading
import time
from typing import Callable


class NfcWatcher(threading.Thread):
    """
    Read-only TWN4 watcher.

    Uses elatec_uid_tool.protocol.SimpleProtocolClient if available.
    No NTAG WRITE/configuration write is performed here.
    """

    def __init__(
        self,
        port: str,
        baudrate: int,
        expected_uid: str,
        poll_interval_ms: int,
        emit: Callable,
        state_cb: Callable | None = None,
    ):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.expected_uid = expected_uid.upper().replace(":", "")
        self.poll_interval = max(20, poll_interval_ms) / 1000.0
        self.emit_cb = emit
        self.state_cb = state_cb
        self.stop_event = threading.Event()
        self.last_present = False
        self.last_uid = ""
        self.error = ""
        self.connected = False

    def _emit(self, kind: str, label: str, **data):
        self.emit_cb(kind, label, "TWN4", **data)

    def _state(self):
        if self.state_cb:
            self.state_cb(self.connected, self.error, self.last_present, self.last_uid)

    def run(self):
        try:
            from elatec_uid_tool.protocol import SimpleProtocolClient
        except Exception as exc:
            self.error = f"ElaTool import failed: {exc}"
            self._emit("NFC_ERROR", self.error)
            self._state()
            return

        while not self.stop_event.is_set():
            try:
                with SimpleProtocolClient(
                    self.port,
                    baudrate=self.baudrate,
                    timeout=1.0,
                ) as client:
                    self.connected = True
                    self.error = ""
                    self._emit("NFC_READER_ONLINE", self.port)
                    self._state()

                    while not self.stop_event.is_set():
                        tag = client.search_tag()
                        present = tag is not None
                        uid = tag.id_hex if tag else ""

                        if present and (not self.last_present or uid != self.last_uid):
                            self._emit(
                                "NFC_FIELD",
                                f"TAG {uid}",
                                uid=uid,
                                expected=(uid == self.expected_uid if self.expected_uid else None),
                                tag_type=(tag.tag_type if tag else None),
                            )
                        elif not present and self.last_present:
                            self._emit("NFC_FIELD_OFF", "TAG LOST", uid=self.last_uid)

                        self.last_present = present
                        self.last_uid = uid
                        self._state()
                        time.sleep(self.poll_interval)

            except Exception as exc:
                self.connected = False
                self.error = f"{type(exc).__name__}: {exc}"
                self._emit("NFC_ERROR", self.error)
                self._state()
                time.sleep(2.0)
