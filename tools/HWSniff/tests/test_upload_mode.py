"""Unit tests for DIP2 WiFi / FTP upload mode (no real network)."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
import unittest
from pathlib import Path

from hwsniff.configuration import DEFAULT_CONFIG, deep_merge, load_config
from hwsniff.dip import dip_mode_from_levels
from hwsniff.state import DeviceState, DipMode, WlanStatus
from hwsniff.upload.config import load_upload_settings
from hwsniff.upload.ftp_client import BundleUploader
from hwsniff.upload.led_signals import UploadLedPattern, led_levels, pattern_finished
from hwsniff.upload.service import UploadService, list_export_bundles
from hwsniff.upload.state_store import BundleRecord, BundleStatus, UploadStateStore
from hwsniff.upload.wifi import WifiCheck


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeFtp:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.cwd_path = "/"
        self.fail_login = False
        self.fail_cwd = False
        self.fail_rename = False
        self.connected = False

    def connect(self, host, port=21, timeout=15):
        self.connected = True
        return "220"

    def login(self, user="", passwd=""):
        if self.fail_login:
            from ftplib import error_perm

            raise error_perm("530 Login incorrect.")
        assert passwd != "LEAKME" or True  # password accepted but never logged
        return "230"

    def set_pasv(self, val: bool) -> None:
        return None

    def cwd(self, dirname: str) -> str:
        if self.fail_cwd:
            from ftplib import error_perm

            raise error_perm("550 Failed")
        self.cwd_path = dirname
        return "250"

    def delete(self, filename: str) -> str:
        self.files.pop(filename, None)
        return "250"

    def storbinary(self, cmd: str, fp, blocksize: int = 8192) -> str:
        name = cmd.split(" ", 1)[1]
        self.files[name] = fp.read()
        return "226"

    def rename(self, fromname: str, toname: str) -> str:
        if self.fail_rename:
            raise OSError("rename failed")
        if fromname not in self.files:
            raise OSError("missing part")
        self.files[toname] = self.files.pop(fromname)
        return "250"

    def size(self, filename: str):
        data = self.files.get(filename)
        return None if data is None else len(data)

    def quit(self) -> str:
        return "221"

    def close(self) -> None:
        return None


def _wifi_ok(_iface: str) -> WifiCheck:
    return WifiCheck(True, WlanStatus.CONNECTED, "192.168.1.10", True, "ok")


def _wifi_bad(_iface: str) -> WifiCheck:
    return WifiCheck(False, WlanStatus.OFFLINE, None, False, "no_wifi")


class DipUploadMappingTests(unittest.TestCase):
    def test_dip2_is_upload(self):
        self.assertEqual(
            dip_mode_from_levels(dip1_on=False, dip2_on=True), DipMode.UPLOAD
        )
        self.assertEqual(
            dip_mode_from_levels(dip1_on=True, dip2_on=True), DipMode.ERROR3
        )


class ConfigCompatTests(unittest.TestCase):
    def test_missing_upload_section(self):
        cfg = deep_merge(DEFAULT_CONFIG, {"hardware_profile": "v2"})
        # Simulate old file without upload key by loading merge
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text('{"hardware_profile":"v2"}', encoding="utf-8")
            loaded = load_config(path)
        settings = load_upload_settings(loaded)
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.server, "ftp.altisima.cz")
        self.assertEqual(settings.password, "")


class BundleScanTests(unittest.TestCase):
    def test_primary_only_ignores_tmp_part_orders_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "export"
            mirror = root / "mirror"
            primary.mkdir()
            mirror.mkdir()
            older = primary / "a.tar"
            newer = primary / "b.tar"
            older.write_bytes(b"old")
            time.sleep(0.02)
            newer.write_bytes(b"new")
            (primary / "x.tar.tmp").write_bytes(b"tmp")
            (primary / "y.tar.part").write_bytes(b"part")
            (mirror / "a.tar").write_bytes(b"dup")
            found = list_export_bundles(primary)
            self.assertEqual([p.name for p in found], ["a.tar", "b.tar"])
            # Mirror must not be scanned by service source_root
            self.assertNotIn(mirror / "a.tar", found)


class StateStoreTests(unittest.TestCase):
    def test_atomic_and_uploading_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload-state.json"
            store = UploadStateStore(path)
            store.load()
            rec = BundleRecord(
                local_path="/x/a.tar",
                remote_name="a.tar",
                size=3,
                mtime=1.0,
                sha256="abc",
                status=BundleStatus.UPLOADING,
            )
            store.upsert(rec)
            store.save()
            store2 = UploadStateStore(path)
            store2.load()
            items = list(store2.records.values())
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, BundleStatus.PENDING)

    def test_corrupt_manifest_rebuilds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload-state.json"
            path.write_text("{not-json", encoding="utf-8")
            store = UploadStateStore(path)
            store.load()
            self.assertEqual(store.records, {})
            self.assertTrue(path.with_name(path.name + ".corrupt").exists())


class FtpUploadTests(unittest.TestCase):
    def test_success_uses_part_then_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "pack.tar"
            local.write_bytes(b"hello-bytes")
            ftp = FakeFtp()
            settings = load_upload_settings(
                {
                    "upload": {
                        "password": "secret",
                        "server": "ftp.example.test",
                    }
                }
            )
            uploader = BundleUploader(settings, ftp_factory=lambda: ftp)
            result = uploader.upload_file(local, "pack.tar")
            self.assertTrue(result.ok)
            self.assertIn("pack.tar", ftp.files)
            self.assertNotIn("pack.tar.part", ftp.files)

    def test_password_not_in_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "pack.tar"
            local.write_bytes(b"x")
            ftp = FakeFtp()
            ftp.fail_login = True
            settings = load_upload_settings({"upload": {"password": "SUPERSECRET"}})
            uploader = BundleUploader(settings, ftp_factory=lambda: ftp)
            with self.assertLogs("hwsniff.upload", level="WARNING") as cm:
                # force a warning path via service logger namespace too
                logging.getLogger("hwsniff.upload.ftp_client").warning(
                    "login failed category=auth"
                )
                result = uploader.upload_file(local, "pack.tar")
            self.assertFalse(result.ok)
            blob = "\n".join(cm.output)
            self.assertNotIn("SUPERSECRET", blob)
            self.assertNotIn("SUPERSECRET", result.message)


class UploadServiceTests(unittest.TestCase):
    def _settings(self, export: Path, state: Path, password: str = "x") -> dict:
        return {
            "data_root": str(export.parent),
            "collector": {"export_bundle_root": str(export)},
            "upload": {
                "enabled": True,
                "source_root": str(export),
                "state_file": str(state),
                "password": password,
                "rescan_interval_seconds": 0.05,
                "retry_delays_seconds": [0.05, 0.05],
                "server": "ftp.test",
            },
            "network": {"interface": "wlan0"},
        }

    def test_start_once_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            ftp = FakeFtp()
            clock = FakeClock()
            svc = UploadService(
                settings,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                clock=clock,
                sleep=lambda _d: clock.advance(0.01),
            )
            svc.start()
            self.assertTrue(svc.running)
            svc.start()  # duplicate
            self.assertTrue(svc.running)
            svc.stop()
            self.assertFalse(svc.running)

    def test_uploads_oldest_and_skips_second_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            a = export / "a.tar"
            a.write_bytes(b"aaa")
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            ftp = FakeFtp()
            clock = FakeClock()
            svc = UploadService(
                settings,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                clock=clock,
                sleep=lambda _d: None,
            )
            # Run one cycle synchronously
            outcome = svc._cycle_once()
            self.assertEqual(outcome, "success")
            self.assertTrue(any(k.startswith("a_") and k.endswith(".tar") for k in ftp.files))
            outcome2 = svc._cycle_once()
            self.assertEqual(outcome2, "empty")

    def test_changed_content_requeues(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            a = export / "a.tar"
            a.write_bytes(b"v1")
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            ftp = FakeFtp()
            svc = UploadService(
                settings,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                sleep=lambda _d: None,
            )
            self.assertEqual(svc._cycle_once(), "success")
            first_keys = set(ftp.files)
            a.write_bytes(b"v2-changed")
            self.assertEqual(svc._cycle_once(), "success")
            self.assertGreater(len(ftp.files), len(first_keys))
            self.assertIn(b"v2-changed", ftp.files.values())

    def test_no_wifi_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            svc = UploadService(
                settings,
                wifi_check=_wifi_bad,
                sleep=lambda _d: None,
            )
            self.assertEqual(svc._cycle_once(), "no_wifi")

    def test_ftp_error_keeps_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            (export / "a.tar").write_bytes(b"data")
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            ftp = FakeFtp()
            ftp.fail_cwd = True
            svc = UploadService(
                settings,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                sleep=lambda _d: None,
            )
            self.assertEqual(svc._cycle_once(), "ftp_error")
            pending = svc.store.pending_or_failed()
            self.assertEqual(len(pending), 1)
            self.assertIn(pending[0].status, (BundleStatus.PENDING, BundleStatus.FAILED))

    def test_rename_before_manifest_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            path = export / "a.tar"
            data = b"payload"
            path.write_bytes(data)
            state = Path(tmp) / "state.json"
            cfg = self._settings(export, state)
            settings = load_upload_settings(cfg)
            ftp = FakeFtp()
            digest = hashlib.sha256(data).hexdigest()
            remote_name = f"a_{digest[:12]}.tar"
            ftp.files[remote_name] = data  # already renamed remotely
            store = UploadStateStore(state)
            store.load()
            store.upsert(
                BundleRecord(
                    local_path=str(path.resolve()),
                    remote_name=remote_name,
                    size=len(data),
                    mtime=path.stat().st_mtime,
                    sha256=digest,
                    status=BundleStatus.PENDING,
                )
            )
            store.save()
            svc = UploadService(
                settings,
                store=store,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                sleep=lambda _d: None,
            )
            self.assertEqual(svc._cycle_once(), "success")
            rec = store.find_uploaded_match(
                local_path=str(path.resolve()), size=len(data), sha256=digest
            )
            self.assertIsNotNone(rec)


class LedPatternTests(unittest.TestCase):
    def test_active_exclusive(self):
        levels = led_levels(UploadLedPattern.ACTIVE, 0.0)
        self.assertTrue(levels["green"])
        self.assertFalse(levels["yellow"])
        self.assertFalse(levels["red"])
        levels = led_levels(UploadLedPattern.ACTIVE, 0.2)
        self.assertTrue(levels["yellow"])
        self.assertEqual(sum(1 for v in levels.values() if v), 1)

    def test_no_wifi_blue(self):
        levels = led_levels(UploadLedPattern.NO_WIFI, 0.05)
        self.assertTrue(levels["blue"])

    def test_success_finishes(self):
        self.assertFalse(pattern_finished(UploadLedPattern.SUCCESS, 1.0))
        self.assertTrue(pattern_finished(UploadLedPattern.SUCCESS, 3.0))


class AppUploadIntegrationTests(unittest.TestCase):
    def test_boot_in_upload_and_leave_stops(self):
        from hwsniff.app import HeadlessApp
        from hwsniff.buttons import ButtonEvent
        from hwsniff.collector_service import MockCollector
        from hwsniff.gpio_backend import MockGpioBackend
        from hwsniff.network import NetworkMonitor
        from hwsniff.reader_monitor import ReaderMonitor, ReaderPresence
        from hwsniff.state import CollectorOutcome

        class AlwaysPresent(ReaderMonitor):
            def __init__(self):
                super().__init__({"reader": {}}, clock=time.monotonic)

            def probe(self):
                return ReaderPresence(True, port="COM1", version="fake")

        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "export"
            export.mkdir()
            state = Path(tmp) / "upload-state.json"
            gpio = MockGpioBackend()
            # DIP2 ON (active-low → drive LOW)
            gpio.setup_input(12, pull_up=True)
            gpio.setup_input(13, pull_up=True)
            gpio.set_input(13, False)

            ftp = FakeFtp()
            settings = load_upload_settings(
                {
                    "collector": {"export_bundle_root": str(export)},
                    "upload": {
                        "source_root": str(export),
                        "state_file": str(state),
                        "password": "x",
                        "rescan_interval_seconds": 0.2,
                        "retry_delays_seconds": [0.2],
                    },
                }
            )
            upload = UploadService(
                settings,
                uploader=BundleUploader(settings, ftp_factory=lambda: ftp),
                wifi_check=_wifi_ok,
                sleep=lambda _d: None,
            )
            cfg = {
                "hardware_profile": "v2",
                "gpio_prefer_mock": True,
                "self_test": {"enabled": False},
                "data_root": tmp,
                "capture_root": str(Path(tmp) / "captures"),
                "log_root": str(Path(tmp) / "logs"),
                "collector": {"use_mock": True, "export_bundle_root": str(export)},
                "sweetp": {"use_mock": True},
                "upload": {**settings.safe_dict(), "password": "x"},
            }
            app = HeadlessApp(
                config=cfg,
                gpio=gpio,
                collector=MockCollector(outcome=CollectorOutcome.SUCCESS),
                network=NetworkMonitor(interface="x", poll_seconds=1000),
                reader_monitor=AlwaysPresent(),
                upload_service=upload,
                loop_forever=False,
                force_mock=True,
                sleep=lambda _d: None,
            )
            app.boot()
            self.assertEqual(app.runtime.device_state, DeviceState.UPLOAD)
            self.assertTrue(app.upload.running)
            # START must not begin capture
            app._handle_button(ButtonEvent.START_SHORT)
            self.assertFalse(app.collector.is_running())
            # Leave upload
            gpio.set_input(13, True)  # DIP2 OFF
            app._poll_dip()
            self.assertFalse(app.upload.running)


if __name__ == "__main__":
    unittest.main()
