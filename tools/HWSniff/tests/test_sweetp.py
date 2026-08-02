from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead

from hwsniff.legacy.app import HWSniffApp
from hwsniff.configuration import DEFAULT_CONFIG, deep_merge, load_config
from hwsniff.legacy.models import AppState
from hwsniff.legacy.state import AppStateMachine
from hwsniff.legacy.ui import UiAction


VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")
PAGE00_BLOCK = bytes.fromhex("04 36 7F 88 5A 2D 72 80 00 00 00 00 00 00 00 00")


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class FakePort:
    def __init__(self, device="/dev/ttyACM9"):
        self.device = device
        self.description = "ELATEC TWN4"
        self.hwid = "USB VID:PID=09D8:0410"
        self.vid = 0x09D8
        self.pid = 0x0410
        self.manufacturer = "ELATEC"
        self.product = "TWN4"
        self.serial_number = "SN-SWEETP"


class ScriptState:
    def __init__(self):
        self.search_count = 0


class ScriptedClient:
    def __init__(
        self,
        port="X",
        timeout=2.0,
        *,
        present: bool = True,
        uid_hex: str = "04367F5A2D7280",
        fail_every: int | None = None,
        alternate_uid: bool = False,
        raise_on_open: bool = False,
        state: ScriptState | None = None,
        latency_sleep: float = 0.0,
    ):
        self.port = port
        self.timeout = timeout
        self.present = present
        self.uid_hex = uid_hex
        self.fail_every = fail_every
        self.alternate_uid = alternate_uid
        self.raise_on_open = raise_on_open
        self.state = state or ScriptState()
        self.latency_sleep = latency_sleep

    def __enter__(self):
        if self.raise_on_open:
            raise OSError("reader disconnected")
        return self

    def __exit__(self, *a):
        return None

    def search_tag(self, max_id_bytes=32):
        if self.latency_sleep:
            time.sleep(self.latency_sleep)
        if not self.present:
            return None
        self.state.search_count += 1
        if self.fail_every and self.state.search_count % self.fail_every == 0:
            return None
        uid = self.uid_hex
        if self.alternate_uid and self.state.search_count % 2 == 0:
            uid = "04367F5A2D7281"
        return TagRead(0x04, 56, bytes.fromhex(uid))

    def set_rf_off(self):
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        op = tx[0]
        if op == 0x60:
            return with_crc(VERSION)
        if op == 0x30:
            return with_crc(PAGE00_BLOCK)
        if op == 0x3A:
            start, end = tx[1], tx[2]
            return with_crc(bytes((end - start + 1) * 4))
        raise AssertionError(tx.hex())


def make_app(tmp: Path, factory, ports=None, **sweet_overrides):
    sweet = {
        "sample_interval_ms": 20,
        "ui_update_ms": 20,
        "window_size": 20,
        "short_window_size": 5,
        "good_hold_ms": 80,
        "min_samples_for_ok": 5,
        "trend_hold_ms": 0,
        "require_get_version": True,
        "require_page_00": False,
        "require_application_block": False,
        **sweet_overrides,
    }
    cfg = deep_merge(
        DEFAULT_CONFIG,
        {
            "data_root": str(tmp / "data"),
            "capture_root": str(tmp / "data" / "captures"),
            "log_root": str(tmp / "logs"),
            "collector": {"minimum_free_space_mb": 0},
            "sweetp": sweet,
        },
    )
    return HWSniffApp(
        config=cfg,
        headless=True,
        list_ports=lambda: ports if ports is not None else [FakePort()],
        client_factory=factory,
    )


def wait_state(app, states, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.pump()
        if app.state.get().state in states:
            return True
        time.sleep(0.02)
    return False


class SweetPAppTests(unittest.TestCase):
    def test_button_from_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                self.assertIn("sweetp", app.state.allowed_actions())
                app.handle_action(UiAction("sweetp"))
                self.assertTrue(
                    wait_state(
                        app,
                        {
                            AppState.SWEETP_WAITING_FOR_TAG,
                            AppState.SWEETP_CHECKING,
                            AppState.SWEETP_GOOD_POSITION,
                            AppState.SWEETP_UNSTABLE_POSITION,
                            AppState.SWEETP_STARTING,
                        },
                    )
                )
            finally:
                app.close()

    def test_hidden_without_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t), ports=[])
            try:
                app.initialize()
                self.assertEqual(app.state.get().state, AppState.READER_MISSING)
                self.assertNotIn("sweetp", app.state.allowed_actions())
            finally:
                app.close()

    def test_live_reaches_position_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                before = app.state.get().ok_count
                app.handle_action(UiAction("sweetp"))
                self.assertTrue(wait_state(app, {AppState.SWEETP_GOOD_POSITION}, 4.0))
                snap = app.state.get()
                self.assertGreaterEqual(snap.sweetp_current_quality, 85)
                self.assertEqual(app.state.get().ok_count, before)
                self.assertEqual(list((root / "data" / "captures").glob("*")), [])
            finally:
                app.close()

    def test_no_tag_stays_waiting_or_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t, present=False),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.25)
                app.pump()
                snap = app.state.get()
                self.assertIn(
                    snap.state,
                    {
                        AppState.SWEETP_WAITING_FOR_TAG,
                        AppState.SWEETP_CHECKING,
                        AppState.SWEETP_UNSTABLE_POSITION,
                    },
                )
                self.assertLess(snap.sweetp_current_quality, 50)
            finally:
                app.close()

    def test_cancel_stops_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.1)
                app.pump()
                app.handle_action(UiAction("sweetp_cancel"))
                time.sleep(0.1)
                app.pump()
                self.assertEqual(app.state.get().state, AppState.READY)
                self.assertFalse(app.sweetp.running)
            finally:
                app.close()

    def test_reader_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode = {"fail": False}

            def factory(p, t):
                if mode["fail"]:
                    return ScriptedClient(p, t, raise_on_open=True)
                return ScriptedClient(p, t, present=False)

            app = make_app(Path(tmp), factory)
            try:
                app.initialize()
                app._selected_port = "/dev/ttyACM9"
                mode["fail"] = True
                app._sweetp_session = True
                app.state.set_state(AppState.SWEETP_STARTING)
                app.sweetp.start(app._selected_port, app.config)
                self.assertTrue(wait_state(app, {AppState.SWEETP_READER_ERROR}))
            finally:
                app.close()

    def test_cannot_start_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp), lambda p, t: ScriptedClient(p, t, present=False)
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.05)
                app.pump()
                app.handle_action(UiAction("start"))
                self.assertTrue(app.sweetp.running)
                self.assertFalse(app.collector.running)
            finally:
                app.close()

    def test_cannot_sweetp_during_collection(self):
        gate = threading.Event()

        class GatedMissingClient(ScriptedClient):
            def search_tag(self, max_id_bytes=32):
                gate.wait(timeout=2.0)
                return None

        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: GatedMissingClient(p, t, present=False),
            )
            try:
                gate.set()
                app.initialize()
                gate.clear()
                app.handle_action(UiAction("start"))
                time.sleep(0.05)
                app.pump()
                self.assertTrue(app.collector.running)
                app.handle_action(UiAction("sweetp"))
                self.assertFalse(app.sweetp.running)
            finally:
                gate.set()
                app.close()

    def test_legacy_config_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(
                '{"sweetp": {"probe_interval_ms": 120, "probe_attempts": 8}}',
                encoding="utf-8",
            )
            cfg = load_config(path)
            self.assertEqual(cfg["sweetp"]["probe_interval_ms"], 120)
            self.assertIn("window_size", cfg["sweetp"])
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t, present=False))
            try:
                app.initialize()
                app.config = deep_merge(app.config, {"sweetp": cfg["sweetp"]})
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.1)
                app.pump()
                self.assertTrue(app.sweetp.running)
            finally:
                app.close()

    def test_done_returns_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                wait_state(app, {AppState.SWEETP_GOOD_POSITION}, 4.0)
                app.handle_action(UiAction("sweetp_done"))
                time.sleep(0.1)
                app.pump()
                self.assertEqual(app.state.get().state, AppState.READY)
            finally:
                app.close()

    def test_state_machine_sweetp_actions(self):
        sm = AppStateMachine()
        sm.set_state(AppState.READY)
        self.assertIn("sweetp", sm.allowed_actions())
        sm.set_state(AppState.SWEETP_GOOD_POSITION)
        self.assertIn("sweetp_done", sm.allowed_actions())
        self.assertIn("sweetp_cancel", sm.allowed_actions())


if __name__ == "__main__":
    unittest.main()
