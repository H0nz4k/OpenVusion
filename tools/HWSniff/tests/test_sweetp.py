from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead

from hwsniff.app import HWSniffApp
from hwsniff.configuration import DEFAULT_CONFIG, deep_merge
from hwsniff.models import AppState
from hwsniff.state import AppStateMachine
from hwsniff.sweetp_service import SweetPConfig, SweetPMetrics, SweetPService
from hwsniff.ui import UiAction


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)
PAGE00_BLOCK = bytes.fromhex("04 36 7F 88 5A 2D 72 80 00 00 00 00 00 00 00 00")
VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")


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
        self.tx_count = 0


class ScriptedClient:
    """Scripted transport for SweetP probe tests."""

    def __init__(
        self,
        port="X",
        timeout=2.0,
        *,
        present: bool = True,
        uid_hex: str = "04367F5A2D7280",
        fail_app: bool = False,
        fail_every: int | None = None,
        alternate_uid: bool = False,
        raise_on_open: bool = False,
        state: ScriptState | None = None,
    ):
        self.port = port
        self.timeout = timeout
        self.present = present
        self.uid_hex = uid_hex
        self.fail_app = fail_app
        self.fail_every = fail_every
        self.alternate_uid = alternate_uid
        self.raise_on_open = raise_on_open
        self.state = state or ScriptState()

    def __enter__(self):
        if self.raise_on_open:
            raise OSError("reader disconnected")
        return self

    def __exit__(self, *a):
        return None

    def search_tag(self, max_id_bytes=32):
        if not self.present:
            return None
        self.state.search_count += 1
        uid = self.uid_hex
        if self.alternate_uid and self.state.search_count % 2 == 0:
            uid = "04367F5A2D7281"
        return TagRead(0x04, 56, bytes.fromhex(uid))

    def set_rf_off(self):
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        self.state.tx_count += 1
        if self.fail_every and self.state.tx_count % self.fail_every == 0:
            from elatec_uid_tool.protocol import SerialCommunicationError

            raise SerialCommunicationError("Tag neodpověděl na příkaz (timeout).")
        op = tx[0]
        if op == 0x60:
            return with_crc(VERSION)
        if op == 0x30:
            start = tx[1]
            if start == 0x00:
                return with_crc(PAGE00_BLOCK)
            return with_crc(bytes(16))
        if op == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0x30 and end == 0x37:
                if self.fail_app:
                    from elatec_uid_tool.protocol import SerialCommunicationError

                    raise SerialCommunicationError("Tag neodpověděl na příkaz.")
                return with_crc(REFERENCE_BLOCK)
            return with_crc(bytes((end - start + 1) * 4))
        raise AssertionError(tx.hex())


def make_app(tmp: Path, factory, ports=None, **sweet_overrides):
    sweet = {
        "probe_attempts": 10,
        "probe_interval_ms": 1,
        "minimum_success_ratio": 0.9,
        "minimum_consecutive_successes": 5,
        "auto_repeat_seconds": 0.01,
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


class SweetPUnitTests(unittest.TestCase):
    def test_evaluate_10_of_10(self):
        m = SweetPMetrics(
            attempts=10,
            successful_attempts=10,
            consecutive_successes_max=10,
            success_ratio=1.0,
            uid_stable=True,
            get_version_success_count=10,
            page_00_success_count=10,
            application_block_success_count=10,
            position_ok=True,
        )
        svc = SweetPService(__import__("queue").Queue())
        svc._config = SweetPConfig()
        ok = svc._evaluate_ok(
            m,
            {"04367F5A2D7280"},
            {"00 04 04 05 02 02 13 03"},
            {"04 36 7F 88"},
            {REFERENCE_BLOCK.hex()},
        )
        self.assertTrue(ok)
        self.assertEqual(svc._classify_quality(m), "GOOD")

    def test_evaluate_9_of_10(self):
        m = SweetPMetrics(
            attempts=10,
            successful_attempts=9,
            consecutive_successes_max=8,
            success_ratio=0.9,
            uid_stable=True,
            get_version_success_count=9,
            page_00_success_count=9,
            application_block_success_count=9,
        )
        svc = SweetPService(__import__("queue").Queue())
        svc._config = SweetPConfig()
        self.assertTrue(
            svc._evaluate_ok(
                m,
                {"A"},
                {"V"},
                {"P"},
                {REFERENCE_BLOCK.hex()},
            )
        )

    def test_evaluate_6_of_10_unstable(self):
        m = SweetPMetrics(
            attempts=10,
            successful_attempts=6,
            consecutive_successes_max=4,
            success_ratio=0.6,
            uid_stable=True,
            get_version_success_count=6,
            page_00_success_count=6,
            application_block_success_count=6,
        )
        svc = SweetPService(__import__("queue").Queue())
        svc._config = SweetPConfig()
        self.assertFalse(
            svc._evaluate_ok(
                m,
                {"A"},
                {"V"},
                {"P"},
                {REFERENCE_BLOCK.hex()},
            )
        )


class SweetPAppTests(unittest.TestCase):
    def test_button_from_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                self.assertIn("sweetp", app.state.allowed_actions())
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 2
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state in (
                        AppState.SWEETP_WAITING_FOR_TAG,
                        AppState.SWEETP_CHECKING,
                        AppState.SWEETP_GOOD_POSITION,
                    ):
                        break
                    time.sleep(0.02)
                self.assertIn(
                    app.state.get().state,
                    {
                        AppState.SWEETP_WAITING_FOR_TAG,
                        AppState.SWEETP_CHECKING,
                        AppState.SWEETP_GOOD_POSITION,
                        AppState.SWEETP_STARTING,
                    },
                )
            finally:
                app.close()

    def test_hidden_without_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t),
                ports=[],
            )
            try:
                app.initialize()
                self.assertEqual(app.state.get().state, AppState.READER_MISSING)
                self.assertNotIn("sweetp", app.state.allowed_actions())
            finally:
                app.close()

    def test_stable_position_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = make_app(root, lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                before_ok = app.state.get().ok_count
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 3
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_GOOD_POSITION:
                        break
                    time.sleep(0.02)
                self.assertEqual(app.state.get().state, AppState.SWEETP_GOOD_POSITION)
                self.assertEqual(app.state.get().ok_count, before_ok)
                captures = list((root / "data" / "captures").glob("*"))
                self.assertEqual(captures, [])
                index = root / "data" / "index.csv"
                self.assertFalse(index.exists())
            finally:
                app.close()

    def test_unstable_fail_app_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t, fail_app=True),
                minimum_success_ratio=0.9,
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 3
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_UNSTABLE_POSITION:
                        break
                    time.sleep(0.02)
                self.assertEqual(
                    app.state.get().state, AppState.SWEETP_UNSTABLE_POSITION
                )
            finally:
                app.close()

    def test_alternating_uid_unstable(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = ScriptState()
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(
                    p, t, alternate_uid=True, state=shared
                ),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 3
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_UNSTABLE_POSITION:
                        break
                    time.sleep(0.02)
                self.assertEqual(
                    app.state.get().state, AppState.SWEETP_UNSTABLE_POSITION
                )
            finally:
                app.close()

    def test_no_tag_stays_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t, present=False),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.2)
                app.pump()
                self.assertEqual(
                    app.state.get().state, AppState.SWEETP_WAITING_FOR_TAG
                )
            finally:
                app.close()

    def test_cancel_during_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t, present=False),
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.05)
                app.pump()
                app.handle_action(UiAction("sweetp_cancel"))
                time.sleep(0.1)
                app.pump()
                self.assertEqual(app.state.get().state, AppState.READY)
                self.assertFalse(app.sweetp.running)
            finally:
                app.close()

    def test_cancel_during_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(
                Path(tmp),
                lambda p, t: ScriptedClient(p, t),
                probe_interval_ms=50,
            )
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 2
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_CHECKING:
                        break
                    time.sleep(0.01)
                app.handle_action(UiAction("sweetp_cancel"))
                time.sleep(0.15)
                app.pump()
                self.assertEqual(app.state.get().state, AppState.READY)
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
                self.assertEqual(app.state.get().state, AppState.READY)
                # Keep autodetection healthy, then fail only SweetP opens.
                app._selected_port = "/dev/ttyACM9"
                mode["fail"] = True
                app._sweetp_session = True
                app.state.set_state(AppState.SWEETP_STARTING)
                app.sweetp.start(app._selected_port, app.config)
                deadline = time.time() + 2
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_READER_ERROR:
                        break
                    time.sleep(0.02)
                self.assertEqual(app.state.get().state, AppState.SWEETP_READER_ERROR)
            finally:
                app.close()

    def test_cannot_start_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t, present=False))
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                time.sleep(0.05)
                app.pump()
                app.handle_action(UiAction("start"))
                self.assertTrue(app.sweetp.running)
                self.assertFalse(app.collector.running)
                self.assertIn(app.state.get().state, {
                    AppState.SWEETP_WAITING_FOR_TAG,
                    AppState.SWEETP_STARTING,
                })
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
                # Autodetect handshake must not block on the gate.
                gate.set()
                app.initialize()
                gate.clear()
                app.handle_action(UiAction("start"))
                time.sleep(0.05)
                app.pump()
                self.assertTrue(app.collector.running)
                app.handle_action(UiAction("sweetp"))
                self.assertFalse(app.sweetp.running)
                self.assertEqual(app.state.get().state, AppState.WAITING_FOR_TAG)
            finally:
                gate.set()
                app.close()

    def test_no_write_tokens_in_sweetp(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "hwsniff"
            / "sweetp_service.py"
        )
        text = path.read_text(encoding="utf-8")
        # Ignore string literals used only in comments about forbidden APIs.
        code_lines = [
            line
            for line in text.splitlines()
            if not line.strip().startswith("#")
            and "FORBIDDEN" not in line
        ]
        code = "\n".join(code_lines)
        for token in (
            ".write(",
            "fast_write",
            "compatibility_write",
            "pwd_auth",
            "read_sram",
            "RSSI",
            "signal strength",
        ):
            self.assertNotIn(token, code)

    def test_done_returns_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), lambda p, t: ScriptedClient(p, t))
            try:
                app.initialize()
                app.handle_action(UiAction("sweetp"))
                deadline = time.time() + 3
                while time.time() < deadline:
                    app.pump()
                    if app.state.get().state == AppState.SWEETP_GOOD_POSITION:
                        break
                    time.sleep(0.02)
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
        sm.set_state(AppState.SWEETP_UNSTABLE_POSITION)
        self.assertIn("sweetp_retry", sm.allowed_actions())


if __name__ == "__main__":
    unittest.main()
