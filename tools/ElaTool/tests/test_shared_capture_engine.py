"""Same fake reader → identical phase outcomes via CaptureProbe and FieldCollector."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.field_collector import (
    CollectorConfig,
    FieldCollector,
    FinishStatus,
)
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead
from elatec_uid_tool.readonly_capture import CaptureProbe, ProbeConfig
from elatec_uid_tool.readonly_capture.status import OverallStatus, PhaseStatus


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)
VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")
UID = bytes.fromhex("04367F5A2D7280")


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class SharedFakeClient:
    open_count = 0

    def __init__(self, port="COM5", timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.closed = False
        self._polls = 0
        SharedFakeClient.open_count += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return None

    def get_version_string(self):
        return "TWN4 Shared Fake"

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


REQUIRED_OK = (
    "reader_info",
    "tag_detection",
    "uid_confirm",
    "identification",
    "eeprom",
    "application",
    "session",
    "verification",
)


class SharedCaptureEngineTests(unittest.TestCase):
    def setUp(self):
        SharedFakeClient.open_count = 0

    def test_pcsniff_and_fieldcollector_same_phase_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pcsniff_out = root / "pcsniff"
            hw_out = root / "hwsniff"

            probe = CaptureProbe(
                ProbeConfig(
                    port="COM5",
                    output=pcsniff_out,
                    tag_timeout=5,
                    retry_count=2,
                    retry_delay_ms=1,
                    session_seconds=0.05,
                    session_interval_ms=1,
                    poll_interval_seconds=0,
                    confirm_reads=3,
                    quiet=True,
                ),
                client_factory=lambda p, t: SharedFakeClient(p, t),
                sleep=lambda _d: None,
            )
            probe_result = probe.run()

            collector = FieldCollector(
                CollectorConfig(
                    capture_root=str(hw_out),
                    data_root=str(root / "data"),
                    allow_duplicate=True,
                    wait_for_removal=False,
                    include_session=True,
                    include_full_dump=True,
                    session_duration_seconds=0.05,
                    session_interval_ms=1,
                    phase_retry_count=2,
                    phase_retry_delay_ms=1,
                    tag_acquire_timeout_seconds=5,
                    poll_interval_seconds=0,
                    export_bundle_root=str(root / "export"),
                ),
                client_factory=lambda p, t: SharedFakeClient(p, t),
                sleep=lambda _d: None,
            )
            field_result = collector.run_once("COM5")

            self.assertEqual(probe_result.overall, OverallStatus.SUCCESS)
            self.assertEqual(
                field_result.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY
            )
            self.assertEqual(probe_result.uid, "04367F5A2D7280")
            self.assertEqual(field_result.uid, "04367F5A2D7280")

            for phase in REQUIRED_OK:
                self.assertEqual(
                    probe_result.phase_statuses.get(phase),
                    PhaseStatus.OK.value,
                    msg=f"probe phase {phase}",
                )

            ui = field_result.phase_status
            self.assertEqual(ui.get("identification"), "ok")
            self.assertEqual(ui.get("eeprom"), "ok")
            self.assertEqual(ui.get("application"), "ok")
            self.assertEqual(ui.get("session"), "ok")
            self.assertEqual(ui.get("verify"), "ok")

            # One serial session per tool run.
            self.assertEqual(SharedFakeClient.open_count, 2)
            self.assertTrue(probe_result.port_closed)
            self.assertTrue(probe_result.output_dir.name.endswith("UID-04367F5A2D7280"))
            self.assertTrue(
                Path(field_result.directory).name.endswith("UID-04367F5A2D7280")
            )
            self.assertTrue(
                (probe_result.output_dir / "phases" / "eeprom.json").exists()
            )
            self.assertTrue(
                (Path(field_result.directory) / "phases" / "application.json").exists()
            )
            self.assertEqual(probe_result.errors, [])
            self.assertEqual(field_result.errors, [])


if __name__ == "__main__":
    unittest.main()
