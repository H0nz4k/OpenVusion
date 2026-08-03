"""Capture engine tests via shared ElaTool fake reader (PCSniff parity)."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead
from elatec_uid_tool.readonly_capture import CaptureProbe, ProbeConfig
from elatec_uid_tool.readonly_capture.status import OverallStatus

from hwsniff.collector_service import CaptureCollector, MockCollector
from hwsniff.state import CollectorOutcome, DipMode, READ_PHASE_STEPS


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)
VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")
UID = bytes.fromhex("04367F5A2D7280")


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class FakeClient:
    open_count = 0

    def __init__(self, port="COM5", timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.closed = False
        self._polls = 0
        FakeClient.open_count += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return None

    def get_version_string(self):
        return "TWN4 HWSniff Fake"

    def get_device_type(self):
        return 0x85

    def get_supported_tag_types(self):
        return (0, 0xFFFFFFFF)

    def set_rf_off(self):
        return None

    def search_tag(self, max_id_bytes=32):
        self._polls += 1
        if self._polls <= 1:
            return None
        return TagRead(0x04, len(UID) * 8, UID)

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        op = tx[0]
        if op == 0x60:
            return with_crc(VERSION)
        if op == 0x30:
            return with_crc(bytes(16))
        if op == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0x30 and end == 0x37:
                return with_crc(REFERENCE_BLOCK)
            if start == 0xEC:
                return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
            return with_crc(bytes((end - start + 1) * 4))
        raise AssertionError(tx.hex())


class PhaseEventFake(FakeClient):
    """Same as FakeClient; used to collect phase_started events."""


class CaptureProbePhaseTests(unittest.TestCase):
    def test_phase_started_events_and_success(self):
        FakeClient.open_count = 0
        started: list[str] = []
        completed: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            probe = CaptureProbe(
                ProbeConfig(
                    port="COM5",
                    output=Path(tmp),
                    raw_trace=True,
                    tag_timeout=2.0,
                    session_seconds=0.15,
                    session_interval_ms=40,
                    quiet=True,
                ),
                client_factory=lambda p, t: FakeClient(p, t),
                sleep=lambda _d: None,
                on_event=lambda name, payload: (
                    started.append(payload["phase"])
                    if name == "phase_started"
                    else completed.append(payload.get("phase", ""))
                    if name == "phase_complete"
                    else None
                ),
            )
            result = probe.run()
        self.assertEqual(result.overall, OverallStatus.SUCCESS)
        self.assertEqual(result.uid, "04367F5A2D7280")
        for phase in READ_PHASE_STEPS:
            self.assertIn(phase, started)
        self.assertEqual(FakeClient.open_count, 1)
        self.assertTrue(result.port_closed)

    def test_stop_during_eeprom(self):
        stop = threading.Event()
        chunk_events = {"n": 0}

        class SlowFake(FakeClient):
            def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
                op = tx[0]
                if op == 0x3A and tx[1] == 0x00:
                    chunk_events["n"] += 1
                    if chunk_events["n"] >= 2:
                        stop.set()
                return super().iso14443_3_tdx(tx, max_rx_bytes, timeout_ms)

        with tempfile.TemporaryDirectory() as tmp:
            probe = CaptureProbe(
                ProbeConfig(
                    port="COM5",
                    output=Path(tmp),
                    raw_trace=False,
                    tag_timeout=2.0,
                    session_seconds=0.1,
                    quiet=True,
                ),
                client_factory=lambda p, t: SlowFake(p, t),
                sleep=lambda _d: None,
                stop_event=stop,
            )
            result = probe.run()
        self.assertTrue(result.aborted or result.overall != OverallStatus.FAILED or result.uid)
        # Must keep usable partial data when aborted mid-eeprom
        self.assertIsNotNone(result.uid)


class MockCollectorPhaseTests(unittest.TestCase):
    def test_mock_emits_six_phases(self):
        clock = {"t": 0.0}

        def now():
            return clock["t"]

        phases: list[str] = []
        coll = MockCollector(phase_seconds=0.1, save_seconds=0.05, clock=now)
        coll.on_phase_started = phases.append
        coll.start(DipMode.MAIN)
        for i in range(30):
            clock["t"] = i * 0.1
            coll.tick()
        self.assertEqual(phases, list(READ_PHASE_STEPS.keys()))
        self.assertFalse(coll.is_running())
        self.assertEqual(coll.get_result().outcome, CollectorOutcome.SUCCESS)

    def test_mock_stop_cancels(self):
        clock = {"t": 0.0}
        coll = MockCollector(phase_seconds=1.0, clock=lambda: clock["t"])
        coll.start(DipMode.MAIN)
        coll.request_stop()
        coll.tick()
        self.assertEqual(coll.get_result().outcome, CollectorOutcome.CANCELLED)


class CaptureCollectorThreadTests(unittest.TestCase):
    def test_capture_collector_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "capture_root": tmp,
                "data_root": tmp,
                "collector": {
                    "allow_duplicate": True,
                    "include_full_dump": True,
                    "include_session": True,
                    "session_duration_seconds": 0.15,
                    "session_interval_ms": 40,
                    "tag_acquire_timeout_seconds": 2,
                    "raw_trace": True,
                    "export_bundle_root": None,
                },
                "reader": {"handshake_timeout_seconds": 2, "retry_delay_ms": 10},
            }
            started: list[str] = []
            coll = CaptureCollector(
                cfg, client_factory=lambda p, t: FakeClient(p, t)
            )
            coll.on_phase_started = started.append
            coll.start(DipMode.MAIN, port="COM5")
            deadline = time.time() + 10
            while coll.is_running() and time.time() < deadline:
                time.sleep(0.02)
            result = coll.get_result()
            self.assertIsNotNone(result)
            self.assertEqual(result.outcome, CollectorOutcome.SUCCESS)
            self.assertEqual(result.uid, "04367F5A2D7280")
            self.assertIn("uid_confirm", started)


if __name__ == "__main__":
    unittest.main()
