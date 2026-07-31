from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import SerialCommunicationError, TagRead

from hwsniff.app import HWSniffApp
from hwsniff.configuration import DEFAULT_CONFIG, deep_merge
from hwsniff.models import AppState, FIELD_RESULT_STATES
from hwsniff.ui import UiAction


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class FakePort:
    def __init__(self, device="/dev/ttyACM0"):
        self.device = device
        self.description = "ELATEC TWN4"
        self.hwid = "USB VID:PID=09D8:0410"
        self.vid = 0x09D8
        self.pid = 0x0410
        self.manufacturer = "ELATEC"
        self.product = "TWN4"
        self.serial_number = "SN1"


class TrackingClient:
    open_count = 0
    live = 0

    def __init__(self, port="COM6", timeout=2.0, *, present=True, fail_session=False):
        self.port = port
        self.timeout = timeout
        self.present = present
        self.fail_session = fail_session
        self.closed = False
        TrackingClient.open_count += 1
        TrackingClient.live += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        TrackingClient.live = max(0, TrackingClient.live - 1)
        return None

    def search_tag(self, max_id_bytes=32):
        if not self.present:
            return None
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self):
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        op = tx[0]
        if op == 0x60:
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if op == 0x30:
            return with_crc(bytes.fromhex("04 36 7F 88 5A 2D 72 80 00 00 00 00 00 00 00 00"))
        if op == 0x3A:
            start, end = tx[1], tx[2]
            if self.fail_session and start == 0xEC:
                raise SerialCommunicationError("session timeout")
            if start == 0x30 and end == 0x37:
                return with_crc(REFERENCE_BLOCK)
            if start == 0xEC:
                return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
            return with_crc(bytes((end - start + 1) * 4))
        raise AssertionError(tx.hex())


def make_cfg(root: Path, **collector_extra):
    coll = {
        "minimum_free_space_mb": 0,
        "application_samples": 1,
        "session_duration_seconds": 0.05,
        "include_session": True,
        "include_full_dump": True,
        "full_dump_samples": 1,
        "wait_for_removal": False,
        "allow_duplicate": True,
        "export_bundle_root": str(root / "export"),
        "phase_retry_count": 3,
        "phase_retry_delay_ms": 1,
        "tag_acquire_timeout_seconds": 2,
        "capture_timeout_seconds": 30,
    }
    coll.update(collector_extra)
    return deep_merge(
        DEFAULT_CONFIG,
        {
            "data_root": str(root / "data"),
            "capture_root": str(root / "data" / "captures"),
            "log_root": str(root / "logs"),
            "collector": coll,
        },
    )


def pump_until(app: HWSniffApp, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.pump()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class OneShotWorkflowTests(unittest.TestCase):
    def setUp(self):
        TrackingClient.open_count = 0
        TrackingClient.live = 0

    def test_start_runs_exactly_one_capture_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = HWSniffApp(
                config=make_cfg(root),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: TrackingClient(p, t),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertTrue(
                    pump_until(
                        app,
                        lambda: app.state.get().state in FIELD_RESULT_STATES,
                    )
                )
                self.assertFalse(app.collector.running)
                self.assertEqual(TrackingClient.live, 0)
                snap = app.state.get()
                self.assertIn(snap.state, (AppState.SUCCESS, AppState.WARNING))
                self.assertNotIn("další", (snap.progress or "").lower())
                self.assertNotIn("Přiložte další", snap.message)
                self.assertEqual(snap.message in ("HOTOVO", "HOTOVO S CHYBAMI"), True)
            finally:
                app.close()

    def test_completed_with_errors_ends_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = HWSniffApp(
                config=make_cfg(root, include_session=True),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: TrackingClient(p, t, fail_session=True),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertTrue(
                    pump_until(
                        app, lambda: app.state.get().state in FIELD_RESULT_STATES
                    )
                )
                self.assertFalse(app.collector.running)
                self.assertEqual(app.state.get().state, AppState.WARNING)
                self.assertEqual(app.state.get().message, "HOTOVO S CHYBAMI")
                self.assertGreaterEqual(app.state.get().capture_phase_errors, 1)
            finally:
                app.close()

    def test_new_tag_starts_fresh_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = HWSniffApp(
                config=make_cfg(root),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: TrackingClient(p, t),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertTrue(
                    pump_until(
                        app, lambda: app.state.get().state in FIELD_RESULT_STATES
                    )
                )
                first_opens = TrackingClient.open_count
                app.handle_action(UiAction("new_tag"))
                self.assertTrue(
                    pump_until(
                        app,
                        lambda: app.state.get().state in FIELD_RESULT_STATES
                        and TrackingClient.open_count > first_opens,
                    )
                )
                self.assertFalse(app.collector.running)
            finally:
                app.close()

    def test_start_ignored_while_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            class SlowClient(TrackingClient):
                def search_tag(self, max_id_bytes=32):
                    time.sleep(0.15)
                    return super().search_tag(max_id_bytes)

            app = HWSniffApp(
                config=make_cfg(root, include_full_dump=False, include_session=False),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: SlowClient(p, t),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertTrue(app.collector.running)
                opens = TrackingClient.open_count
                app.handle_action(UiAction("start"))
                self.assertEqual(TrackingClient.open_count, opens)
                pump_until(app, lambda: not app.collector.running)
            finally:
                app.close()

    def test_stop_aborts_active_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            class IdleClient(TrackingClient):
                def search_tag(self, max_id_bytes=32):
                    return None

            app = HWSniffApp(
                config=make_cfg(root, tag_acquire_timeout_seconds=10),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: IdleClient(p, t, present=False),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertTrue(app.collector.running)
                app.handle_action(UiAction("stop"))
                self.assertFalse(app.collector.running)
                self.assertEqual(app.state.get().state, AppState.READY)
                self.assertEqual(TrackingClient.live, 0)
            finally:
                app.close()

    def test_fatal_reader_error_allows_new_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"n": 0}

            def factory(p, t):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("port busy")
                return TrackingClient(p, t)

            app = HWSniffApp(
                config=make_cfg(root, include_full_dump=False, include_session=False),
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=factory,
            )
            try:
                app.initialize()
                # Handshake uses factory too — force start path with selected port.
                app._selected_port = "/dev/ttyACM0"
                app.state.set_state(AppState.READY, reader_label="READER READY")
                app.collector.start(app._selected_port, app.config)
                self.assertTrue(
                    pump_until(
                        app,
                        lambda: app.state.get().state in FIELD_RESULT_STATES
                        or app.state.get().state == AppState.FAILURE,
                    )
                )
                self.assertFalse(app.collector.running)
                app.state.set_state(AppState.READY, reader_label="READER READY")
                app.handle_action(UiAction("start"))
                self.assertTrue(
                    pump_until(
                        app, lambda: app.state.get().state in FIELD_RESULT_STATES
                    )
                )
            finally:
                app.close()

    def test_result_screen_has_new_tag_action(self):
        sm_actions = __import__(
            "hwsniff.state", fromlist=["AppStateMachine"]
        ).AppStateMachine()
        sm_actions.set_state(AppState.SUCCESS)
        self.assertIn("new_tag", sm_actions.allowed_actions())
        self.assertIn("detail", sm_actions.allowed_actions())
        self.assertNotIn("stop", sm_actions.allowed_actions())


if __name__ == "__main__":
    unittest.main()
