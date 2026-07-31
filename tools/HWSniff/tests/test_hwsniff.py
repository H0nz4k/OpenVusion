from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead

from hwsniff.app import HWSniffApp
from hwsniff.configuration import DEFAULT_CONFIG, deep_merge, load_config
from hwsniff.models import AppState
from hwsniff.state import AppStateMachine
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


class FakeClient:
    def __init__(self, port="COM6", timeout=2.0):
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def search_tag(self, max_id_bytes=32):
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
            if start == 0x30 and end == 0x37:
                return with_crc(REFERENCE_BLOCK)
            if start == 0xEC:
                return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
            return with_crc(bytes((end - start + 1) * 4))
        raise AssertionError(tx.hex())


class HWSniffTests(unittest.TestCase):
    def test_config_defaults_and_merge(self):
        cfg = load_config(None)
        self.assertEqual(cfg["display"]["width"], 480)
        merged = deep_merge(DEFAULT_CONFIG, {"ui": {"success_display_seconds": 9}})
        self.assertEqual(merged["ui"]["success_display_seconds"], 9)
        self.assertEqual(merged["display"]["height"], 320)

    def test_invalid_config_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_state_machine_transitions(self):
        sm = AppStateMachine()
        sm.set_state(AppState.READY)
        self.assertIn("start", sm.allowed_actions())
        sm.set_state(AppState.WAITING_FOR_TAG)
        self.assertIn("stop", sm.allowed_actions())
        sm.set_state(AppState.STORAGE_ERROR)
        self.assertIn("retry", sm.allowed_actions())

    def test_boot_to_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = deep_merge(
                DEFAULT_CONFIG,
                {
                    "data_root": str(root / "data"),
                    "capture_root": str(root / "data" / "captures"),
                    "log_root": str(root / "logs"),
                    "collector": {"minimum_free_space_mb": 0},
                },
            )
            app = HWSniffApp(
                config=cfg,
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: FakeClient(p, t),
            )
            try:
                app.initialize()
                self.assertEqual(app.state.get().state, AppState.READY)
                self.assertIn("READER READY", app.state.get().reader_label)
            finally:
                app.close()

    def test_reader_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = deep_merge(
                DEFAULT_CONFIG,
                {
                    "data_root": str(root / "data"),
                    "capture_root": str(root / "captures"),
                    "log_root": str(root / "logs"),
                    "collector": {"minimum_free_space_mb": 0},
                },
            )
            app = HWSniffApp(
                config=cfg,
                headless=True,
                list_ports=lambda: [],
                client_factory=lambda p, t: FakeClient(p, t),
            )
            try:
                app.initialize()
                self.assertEqual(app.state.get().state, AppState.READER_MISSING)
            finally:
                app.close()

    def test_start_stop_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = deep_merge(
                DEFAULT_CONFIG,
                {
                    "data_root": str(root / "data"),
                    "capture_root": str(root / "data" / "captures"),
                    "log_root": str(root / "logs"),
                    "collector": {
                        "minimum_free_space_mb": 0,
                        "application_samples": 1,
                        "session_duration_seconds": 0,
                        "include_session": False,
                        "wait_for_removal": False,
                    },
                },
            )

            class IdleClient(FakeClient):
                def search_tag(self, max_id_bytes=32):
                    return None

            app = HWSniffApp(
                config=cfg,
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: IdleClient(p, t),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                self.assertEqual(app.state.get().state, AppState.WAITING_FOR_TAG)
                time.sleep(0.1)
                app.pump()
                self.assertTrue(app.collector.running)
                app.handle_action(UiAction("stop"))
                time.sleep(0.05)
                self.assertFalse(app.collector.running)
            finally:
                app.close()

    def test_shutdown_confirm_path(self):
        sm = AppStateMachine()
        sm.set_state(AppState.READY)
        sm.set_state(AppState.SHUTDOWN_CONFIRM)
        self.assertIn("shutdown_confirm", sm.allowed_actions())

    def test_no_com6_hardcode_in_package(self):
        root = Path(__file__).resolve().parents[1] / "src" / "hwsniff"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("COM6", text)
            self.assertNotIn("/dev/ttyACM0", text)

    def test_systemd_unit_has_restart(self):
        unit = (
            Path(__file__).resolve().parents[1] / "systemd" / "hwsniff.service"
        ).read_text(encoding="utf-8")
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("User=hwsniff", unit)
        self.assertIn("/opt/Sniff", unit)

    def test_no_write_api_imports_in_hwsniff(self):
        root = Path(__file__).resolve().parents[1] / "src" / "hwsniff"
        forbidden = (
            "fast_write",
            "compatibility_write",
            "pwd_auth",
            "read_sram",
            "enable_pass_through",
        )
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, msg=f"{path.name} mentions {token}")
            # Allow documentation of forbidden APIs; ban actual calls.
            self.assertNotIn(".write_page(", text, msg=f"{path.name} calls write_page")

    def test_storage_full_blocks_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = deep_merge(
                DEFAULT_CONFIG,
                {
                    "data_root": str(root / "data"),
                    "capture_root": str(root / "data" / "captures"),
                    "log_root": str(root / "logs"),
                    "collector": {"minimum_free_space_mb": 10**12},
                },
            )
            app = HWSniffApp(
                config=cfg,
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: FakeClient(p, t),
            )
            try:
                app.initialize()
                self.assertEqual(app.state.get().state, AppState.STORAGE_ERROR)
                self.assertIn("STORAGE FULL", app.state.get().storage_text)
            finally:
                app.close()

    def test_capture_progress_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = deep_merge(
                DEFAULT_CONFIG,
                {
                    "data_root": str(root / "data"),
                    "capture_root": str(root / "data" / "captures"),
                    "log_root": str(root / "logs"),
                    "collector": {
                        "minimum_free_space_mb": 0,
                        "application_samples": 1,
                        "session_duration_seconds": 0,
                        "include_session": False,
                        "wait_for_removal": False,
                        "allow_duplicate": True,
                    },
                    "ui": {
                        "success_display_seconds": 0.05,
                        "error_display_seconds": 0.05,
                    },
                },
            )
            app = HWSniffApp(
                config=cfg,
                headless=True,
                list_ports=lambda: [FakePort()],
                client_factory=lambda p, t: FakeClient(p, t),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("start"))
                deadline = time.time() + 2.0
                saw_ok = False
                while time.time() < deadline:
                    app.pump()
                    snap = app.state.get()
                    if snap.ok_count >= 1 or snap.last_uid:
                        saw_ok = True
                        break
                    time.sleep(0.05)
                self.assertTrue(saw_ok, "expected at least one capture result")
                app.handle_action(UiAction("stop"))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
