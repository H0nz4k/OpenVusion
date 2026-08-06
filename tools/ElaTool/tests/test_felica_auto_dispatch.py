"""Physical SOLUM findings encoded as shared-engine/HWSniff dispatch tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.field_collector import CollectorConfig, FieldCollector, FinishStatus
from elatec_uid_tool.protocol import TagRead
from elatec_uid_tool.readonly_capture import CaptureProbe, ProbeConfig
from elatec_uid_tool.readonly_capture.status import OverallStatus, PhaseStatus

IDM = bytes.fromhex("02FE42316D8E4C8B")
PMM = bytes.fromhex("FFFF000000FFFF00")
ATTRIBUTE = bytes.fromhex("100201003C000000000000000000004F")
TAIL = {
    54: bytes.fromhex("000000000000000060E2CC67000DCF46"),
    55: bytes.fromhex("5872D9000000000DCF46580600000000"),
    56: bytes.fromhex("7F000000000000000000000000000000"),
}


class FelicaFakeClient:
    iso14443_calls = 0

    def __init__(self, port="COM13", timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        return None

    def get_version_string(self):
        return "TWN4/B1.64/NCF5.20/PRS1.04"

    def get_device_type(self):
        return 11

    def get_supported_tag_types(self):
        return (0, 1655)

    def set_rf_off(self):
        return None

    def search_tag(self, max_id_bytes=32):
        del max_id_bytes
        return TagRead(0x85, 64, IDM)

    def iso14443_3_tdx(self, *args, **kwargs):
        FelicaFakeClient.iso14443_calls += 1
        raise AssertionError("NTAG/ISO14443-3 path must not run for confirmed FeliCa")

    def _request(self, command: bytes) -> bytes:
        if command == bytes.fromhex("1D04FFFF"):
            return b"\x01" + IDM + PMM
        if command == bytes.fromhex("1D04FC12"):
            return b"\x01" + IDM + PMM
        if command == bytes.fromhex("1D0308"):
            return bytes.fromhex("0101FC12")
        if command == bytes.fromhex("1D05010B00"):
            # Physically observed SOLUM behavior: false, yet CHECK succeeds.
            return b"\x00"
        if command[:2] == bytes.fromhex("1D00"):
            frame_len = command[2]
            frame = command[3 : 3 + frame_len]
            self.assert_check_frame(frame)
            block_no = frame[-1]
            data = ATTRIBUTE if block_no == 0 else TAIL.get(block_no, bytes(16))
            felica_response = (
                bytes((0x1D, 0x07))
                + IDM
                + bytes.fromhex("000001")
                + data
            )
            return b"\x01" + bytes((len(felica_response),)) + felica_response
        raise AssertionError(f"Unexpected Simple Protocol command {command.hex().upper()}")

    @staticmethod
    def assert_check_frame(frame: bytes) -> None:
        assert frame[0] == len(frame)
        assert frame[1] == 0x06
        assert frame[2:10] == IDM
        assert frame[10] == 1
        assert frame[11:13] == bytes.fromhex("0B00")
        assert frame[13] == 1
        assert frame[14] == 0x80


class FelicaAutoDispatchTests(unittest.TestCase):
    def setUp(self):
        FelicaFakeClient.iso14443_calls = 0

    def test_captureprobe_dispatches_to_felica_and_keeps_ntag_path_unused(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = CaptureProbe(
                ProbeConfig(
                    port="COM13",
                    output=Path(tmp),
                    tag_timeout=1,
                    retry_count=2,
                    retry_delay_ms=0,
                    session_seconds=0.01,
                    session_interval_ms=0,
                    poll_interval_seconds=0,
                    confirm_reads=3,
                    quiet=True,
                ),
                client_factory=lambda p, t: FelicaFakeClient(p, t),
                sleep=lambda _d: None,
            )
            result = probe.run()

            self.assertEqual(result.overall, OverallStatus.SUCCESS)
            self.assertEqual(result.uid, IDM.hex().upper())
            self.assertEqual(FelicaFakeClient.iso14443_calls, 0)
            self.assertEqual(result.phase_statuses["identification"], PhaseStatus.OK.value)
            self.assertEqual(result.phase_statuses["eeprom"], PhaseStatus.OK.value)
            self.assertEqual(result.phase_statuses["application"], PhaseStatus.OK.value)
            self.assertEqual(result.phase_statuses["session"], PhaseStatus.SKIPPED.value)
            self.assertEqual(result.phase_statuses["verification"], PhaseStatus.OK.value)

            summary = json.loads((result.output_dir / "summary.json").read_text())
            self.assertEqual(summary["technology"], "felica_type3")
            self.assertEqual(summary["felica"]["idm"], IDM.hex().upper())
            self.assertEqual(summary["felica"]["system_codes"], ["0x12FC"])
            self.assertEqual(summary["felica"]["attribute_block"]["nmaxb"], 60)
            self.assertEqual(summary["felica"]["attribute_block"]["ndef_length"], 0)

            app = json.loads(
                (result.output_dir / "phases" / "application.json").read_text()
            )
            self.assertEqual(
                app["research_candidates"]["boundary_6byte_hex"],
                "0DCF465872D9",
            )
            self.assertTrue((result.output_dir / "felica_public.bin").exists())
            self.assertEqual(
                (result.output_dir / "felica_public.bin").stat().st_size,
                61 * 16,
            )

    def test_fieldcollector_hwsniff_path_exposes_felica_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = FieldCollector(
                CollectorConfig(
                    capture_root=str(root / "capture"),
                    data_root=str(root / "data"),
                    allow_duplicate=True,
                    wait_for_removal=False,
                    include_session=True,
                    include_full_dump=True,
                    phase_retry_count=2,
                    phase_retry_delay_ms=0,
                    tag_acquire_timeout_seconds=1,
                    poll_interval_seconds=0,
                    export_bundle_root=None,
                ),
                client_factory=lambda p, t: FelicaFakeClient(p, t),
                sleep=lambda _d: None,
            )
            result = collector.run_once("COM13")

            self.assertEqual(result.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY)
            self.assertEqual(result.uid, IDM.hex().upper())
            self.assertEqual(result.metadata.get("technology"), "felica_type3")
            self.assertEqual(
                result.metadata.get("summary", {}).get("tag_type"),
                "0x85 / FeliCa / NFC Forum Type 3",
            )
            self.assertEqual(result.phase_status.get("identification"), "ok")
            self.assertEqual(result.phase_status.get("eeprom"), "ok")
            self.assertEqual(result.phase_status.get("application"), "ok")
            self.assertEqual(result.phase_status.get("session"), "skipped")
            self.assertEqual(result.phase_status.get("verify"), "ok")
            self.assertEqual(FelicaFakeClient.iso14443_calls, 0)


if __name__ == "__main__":
    unittest.main()
