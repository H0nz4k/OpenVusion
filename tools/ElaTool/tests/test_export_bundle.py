"""Unit tests for capture export bundles (logs + mirror)."""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from elatec_uid_tool.field_collector.models import CollectorConfig
from elatec_uid_tool.field_collector.storage import (
    pack_capture_export,
    resolve_export_tar_path,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_capture(capture_dir: Path) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "summary.json").write_text('{"ok": true}\n', encoding="utf-8")
    (capture_dir / "application.json").write_text("{}\n", encoding="utf-8")


class ExportBundleTests(unittest.TestCase):
    def test_old_collector_config_defaults(self):
        """Legacy configs without new keys keep prior behaviour."""
        cfg = CollectorConfig(capture_root="/tmp/captures")
        self.assertIsNone(cfg.export_bundle_mirror_root)
        self.assertFalse(cfg.include_logs_in_bundle)
        self.assertIsNone(cfg.log_root)

    def test_primary_without_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            _write_capture(capture)
            tar_path = pack_capture_export(capture, export_root=export)
            self.assertTrue(tar_path.exists())
            self.assertEqual(tar_path.parent, export)
            self.assertTrue(tar_path.name.endswith(".tar"))
            self.assertFalse((root / "mirror").exists())

    def test_include_logs_false_skips_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            logs = root / "logs"
            _write_capture(capture)
            logs.mkdir()
            (logs / "hwsniff.log").write_text("line\n", encoding="utf-8")
            tar_path = pack_capture_export(
                capture,
                export_root=export,
                log_root=logs,
                include_logs=False,
            )
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("summary.json", names)
            self.assertNotIn("logs/hwsniff.log", names)
            self.assertFalse(any(n.startswith("logs/") for n in names))

    def test_logs_under_logs_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            logs = root / "log_root"
            _write_capture(capture)
            logs.mkdir()
            (logs / "hwsniff.log").write_text("a\n", encoding="utf-8")
            tar_path = pack_capture_export(
                capture,
                export_root=export,
                log_root=logs,
                include_logs=True,
            )
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("summary.json", names)
            self.assertIn("logs/hwsniff.log", names)

    def test_relative_log_structure_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            logs = root / "log_root"
            _write_capture(capture)
            nested = logs / "archive" / "old"
            nested.mkdir(parents=True)
            (nested / "collector.jsonl").write_text("{}\n", encoding="utf-8")
            tar_path = pack_capture_export(
                capture,
                export_root=export,
                log_root=logs,
                include_logs=True,
            )
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("logs/archive/old/collector.jsonl", names)

    def test_skips_symlinks_and_special_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            logs = root / "log_root"
            _write_capture(capture)
            logs.mkdir()
            (logs / "hwsniff.log").write_text("ok\n", encoding="utf-8")
            link = logs / "link.log"
            try:
                link.symlink_to(logs / "hwsniff.log")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this platform")
            tar_path = pack_capture_export(
                capture,
                export_root=export,
                log_root=logs,
                include_logs=True,
            )
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("logs/hwsniff.log", names)
            self.assertNotIn("logs/link.log", names)

    def test_missing_log_root_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            _write_capture(capture)
            with self.assertLogs(
                "elatec_uid_tool.field_collector.storage", level="WARNING"
            ) as cm:
                tar_path = pack_capture_export(
                    capture,
                    export_root=export,
                    log_root=root / "missing-logs",
                    include_logs=True,
                )
            self.assertTrue(tar_path.exists())
            self.assertTrue(any("log_root" in m for m in cm.output))
            with tarfile.open(tar_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("summary.json", names)
            self.assertFalse(any(n.startswith("logs/") for n in names))

    def test_mirror_identical_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            mirror = root / "mirror"
            _write_capture(capture)
            tar_path = pack_capture_export(
                capture,
                export_root=export,
                mirror_root=mirror,
            )
            mirrored = mirror / tar_path.name
            self.assertTrue(mirrored.exists())
            self.assertEqual(_sha256(tar_path), _sha256(mirrored))

    def test_mirror_failure_keeps_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            _write_capture(capture)
            # File path used as mirror_root → mkdir/copy fails after primary write
            bad_mirror = root / "not-a-dir"
            bad_mirror.write_text("x", encoding="utf-8")
            with self.assertLogs(
                "elatec_uid_tool.field_collector.storage", level="ERROR"
            ) as cm:
                tar_path = pack_capture_export(
                    capture,
                    export_root=export,
                    mirror_root=bad_mirror,
                )
            self.assertTrue(tar_path.exists())
            self.assertTrue(tar_path.stat().st_size > 0)
            self.assertTrue(any("mirror" in m.lower() for m in cm.output))

    def test_atomic_tmp_not_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "cap"
            export = root / "export"
            _write_capture(capture)
            tar_path = pack_capture_export(capture, export_root=export)
            self.assertFalse(tar_path.with_name(tar_path.name + ".tmp").exists())

    def test_resolve_unique_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp)
            a = resolve_export_tar_path(export)
            a.write_bytes(b"x")
            b = resolve_export_tar_path(export)
            self.assertNotEqual(a, b)


class ReaderPreferSerial0Tests(unittest.TestCase):
    def test_preferred_device_path_sorted_first(self):
        from elatec_uid_tool.field_collector.reader import (
            ReaderCandidate,
            detect_readers,
            pick_reader,
        )

        class FakePort:
            def __init__(self, device, **kwargs):
                self.device = device
                self.description = kwargs.get("description", "")
                self.hwid = kwargs.get("hwid", "")
                self.vid = kwargs.get("vid")
                self.pid = kwargs.get("pid")
                self.manufacturer = kwargs.get("manufacturer")
                self.product = kwargs.get("product")
                self.serial_number = kwargs.get("serial_number")

        ports = [
            FakePort("/dev/ttyUSB0", description="other", hwid=""),
            FakePort("/dev/serial0", description="uart", hwid=""),
        ]

        def list_ports():
            return ports

        def client_factory(port, timeout):
            class Ok:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def search_tag(self):
                    return None

            return Ok()

        with mock.patch(
            "elatec_uid_tool.field_collector.reader.os.path.exists",
            return_value=True,
        ):
            found = detect_readers(
                preferred_serial="/dev/serial0",
                list_ports=list_ports,
                client_factory=client_factory,
                verify=True,
                min_score=0,
            )
        self.assertTrue(found)
        self.assertEqual(found[0].device, "/dev/serial0")
        chosen = pick_reader(
            found, preferred_serial="/dev/serial0", auto_detect=True
        )
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen.device, "/dev/serial0")

    def test_matches_preferred_serial_number_still_works(self):
        from elatec_uid_tool.field_collector.reader import (
            ReaderCandidate,
            matches_preferred,
        )

        c = ReaderCandidate(
            device="/dev/ttyACM0",
            description="TWN4",
            hwid="",
            serial_number="ABC123",
            score=100,
            verified=True,
        )
        self.assertTrue(matches_preferred(c, "ABC123"))
        self.assertTrue(matches_preferred(c, "/dev/ttyACM0"))
        self.assertFalse(matches_preferred(c, "/dev/serial0"))


if __name__ == "__main__":
    unittest.main()
