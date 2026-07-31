from __future__ import annotations

import tarfile
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from elatec_uid_tool.field_collector import (
    CollectorConfig,
    FieldCollector,
    FinishStatus,
    detect_readers,
    pick_single_reader,
)
from elatec_uid_tool.field_collector.collector import FieldCollector as FC
from elatec_uid_tool.field_collector.storage import export_bundle_stamp
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import SerialCommunicationError, TagRead


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class FakePort:
    def __init__(self, device, description="", hwid="", vid=None, pid=None, **kwargs):
        self.device = device
        self.description = description
        self.hwid = hwid
        self.vid = vid
        self.pid = pid
        self.manufacturer = kwargs.get("manufacturer")
        self.product = kwargs.get("product")
        self.serial_number = kwargs.get("serial_number")


class FakeClient:
    def __init__(self, port="COM6", timeout=2.0, present=True):
        self.port = port
        self.timeout = timeout
        self.present = present
        self._seen = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def search_tag(self, max_id_bytes=32):
        if not self.present:
            return None
        self._seen += 1
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self):
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        op = tx[0]
        if op == 0x60:
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if op == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0x30 and end == 0x37:
                return with_crc(REFERENCE_BLOCK)
            if start == 0xEC:
                return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
            pages = end - start + 1
            return with_crc(bytes(pages * 4))
        raise AssertionError(tx.hex())


class FieldCollectorTests(unittest.TestCase):
    def test_detect_no_ports(self):
        result = detect_readers(list_ports=lambda: [], verify=False)
        self.assertEqual(result, [])

    def test_detect_one_valid(self):
        ports = [
            FakePort(
                "/dev/ttyACM0",
                description="ELATEC TWN4",
                hwid="USB VID:PID=09D8:0410",
                vid=0x09D8,
                pid=0x0410,
                product="TWN4",
            )
        ]
        result = detect_readers(
            list_ports=lambda: ports,
            client_factory=lambda p, t: FakeClient(p, t),
            verify=True,
        )
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].verified)
        self.assertIsNotNone(pick_single_reader(result))

    def test_detect_multiple(self):
        ports = [
            FakePort("/dev/ttyACM0", hwid="VID:PID=09D8:0410", vid=0x09D8),
            FakePort("/dev/ttyACM1", hwid="VID:PID=09D8:0410", vid=0x09D8),
        ]
        result = detect_readers(
            list_ports=lambda: ports,
            client_factory=lambda p, t: FakeClient(p, t),
        )
        self.assertEqual(len([c for c in result if c.verified]), 2)
        self.assertIsNone(pick_single_reader(result))

    def test_handshake_unverified(self):
        ports = [FakePort("/dev/ttyUSB0", description="Unknown")]

        def bad_factory(p, t):
            raise OSError("fail")

        result = detect_readers(list_ports=lambda: ports, client_factory=bad_factory)
        self.assertTrue(result)
        self.assertFalse(result[0].verified)

    def test_capture_one_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = CollectorConfig(
                capture_root=str(root / "captures"),
                data_root=str(root),
                application_samples=2,
                session_duration_seconds=0.05,
                session_interval_ms=10,
                include_session=True,
                wait_for_removal=False,
                export_bundle_root=None,
            )
            collector = FieldCollector(
                config,
                client_factory=lambda p, t: FakeClient(p, t),
                sleep=lambda s: None,
            )
            result = collector.capture_one("COM6")
            self.assertEqual(result.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY)
            self.assertEqual(result.uid, "04367F5A2D7280")
            self.assertTrue(result.directory)
            self.assertTrue((Path(result.directory) / "hashes.json").exists())
            self.assertTrue((root / "index.jsonl").exists())

    def test_duplicate_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = CollectorConfig(
                capture_root=str(root / "captures"),
                data_root=str(root),
                application_samples=1,
                session_duration_seconds=0,
                include_session=False,
                allow_duplicate=False,
                export_bundle_root=None,
            )
            collector = FieldCollector(
                config,
                client_factory=lambda p, t: FakeClient(p, t),
                sleep=lambda s: None,
            )
            first = collector.capture_one("COM6")
            self.assertEqual(first.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY)
            second = collector.capture_one("COM6")
            self.assertEqual(second.finish_status, FinishStatus.DUPLICATE_SKIPPED)

    def test_resting_tag_needs_rf_wake(self):
        """Tag already in field (SearchTag miss) must be found after SetRFOff."""

        class RestingClient(FakeClient):
            def __init__(self, port="COM6", timeout=2.0):
                super().__init__(port, timeout, present=True)
                self._awake = False
                self.rf_off_calls = 0

            def set_rf_off(self):
                self.rf_off_calls += 1
                self._awake = True

            def search_tag(self, max_id_bytes=32):
                if not self._awake:
                    return None
                self._awake = False
                return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = CollectorConfig(
                capture_root=str(root / "captures"),
                data_root=str(root),
                application_samples=1,
                session_duration_seconds=0,
                include_session=False,
                include_full_dump=True,
                full_dump_samples=1,
                wait_for_removal=False,
                export_bundle_root=None,
            )
            client = RestingClient()
            collector = FieldCollector(
                config,
                client_factory=lambda p, t: client,
                sleep=lambda s: None,
            )
            result = collector.capture_one("COM6")
            self.assertGreaterEqual(client.rf_off_calls, 1)
            self.assertEqual(result.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY)
            self.assertEqual(result.uid, "04367F5A2D7280")
            directory = Path(result.directory)
            self.assertTrue((directory / "dump.bin").exists())
            self.assertTrue((directory / "dump.json").exists())
            self.assertTrue((directory / "application_block.bin").exists())
            self.assertGreater(len((directory / "dump.bin").read_bytes()), 32)

    def test_full_dump_failure_keeps_application_ok(self):
        """EEPROM dump errors must not throw away a good application block."""

        class FlakyDumpClient(FakeClient):
            def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
                op = tx[0]
                if op == 0x3A:
                    start, end = tx[1], tx[2]
                    # Fail the first full-dump chunk once, then succeed via retry path.
                    if start == 0x00 and end == 0x0F:
                        if not getattr(self, "_failed_once", False):
                            self._failed_once = True
                            raise SerialCommunicationError("dump timeout")
                    if start == 0x30 and end == 0x37:
                        return with_crc(REFERENCE_BLOCK)
                    if start == 0xEC:
                        return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
                    pages = end - start + 1
                    return with_crc(bytes(pages * 4))
                return super().iso14443_3_tdx(tx, max_rx_bytes, timeout_ms)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = CollectorConfig(
                capture_root=str(root / "captures"),
                data_root=str(root),
                application_samples=1,
                session_duration_seconds=0,
                include_session=False,
                include_full_dump=True,
                full_dump_samples=1,
                wait_for_removal=False,
                export_bundle_root=None,
            )
            collector = FieldCollector(
                config,
                client_factory=lambda p, t: FlakyDumpClient(p, t),
                sleep=lambda s: None,
            )
            result = collector.capture_one("COM6")
            self.assertIn(
                result.finish_status,
                (
                    FinishStatus.COMPLETED_SUCCESSFULLY,
                    FinishStatus.COMPLETED_WITH_ERRORS,
                ),
            )
            self.assertTrue(result.directory)
            self.assertTrue(
                (Path(result.directory) / "application_block.bin").exists()
            )

    def test_one_tag_sniff_makes_one_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_root = root / "export"
            config = CollectorConfig(
                capture_root=str(root / "captures"),
                data_root=str(root),
                application_samples=1,
                session_duration_seconds=0,
                include_session=False,
                include_full_dump=True,
                full_dump_samples=1,
                wait_for_removal=False,
                export_bundle_root=str(export_root),
            )
            collector = FieldCollector(
                config,
                client_factory=lambda p, t: FakeClient(p, t),
                sleep=lambda s: None,
            )
            result = collector.capture_one("COM6")
            self.assertEqual(result.finish_status, FinishStatus.COMPLETED_SUCCESSFULLY)
            stamp = export_bundle_stamp(datetime.now())
            tar_path = Path(result.metadata["export_bundle"])
            self.assertTrue(tar_path.exists())
            self.assertEqual(tar_path.parent, export_root)
            self.assertTrue(tar_path.name.startswith(stamp[:8]))  # DDMMYYYY…
            self.assertTrue(tar_path.name.endswith(".tar"))
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("application_block.bin", names)
            self.assertIn("dump.bin", names)
            self.assertIn("metadata.json", names)
            self.assertIn("report.txt", names)
            self.assertIn("hashes.json", names)

    def test_no_write_api_on_collector(self):
        for name in FC.FORBIDDEN_METHODS:
            self.assertFalse(hasattr(FieldCollector, name))


if __name__ == "__main__":
    unittest.main()
