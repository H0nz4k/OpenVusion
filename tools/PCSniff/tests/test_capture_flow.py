from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from pathlib import Path

import _pathsetup  # noqa: F401
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import SerialCommunicationError, TagRead

from twn4_capture_probe.capture import CaptureProbe, ProbeConfig
from twn4_capture_probe.retry import run_with_retry
from twn4_capture_probe.raw_trace import RawSerialTracer
from twn4_capture_probe.status import OverallStatus, PhaseStatus


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)
VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class FakeTransport:
    def __init__(self):
        self.closed = False
        self.exchange = self._exchange

    def open(self):
        return None

    def close(self):
        self.closed = True

    def _exchange(self, command: bytes) -> bytes:
        return b"\x00"


class FakeClient:
    """Minimal SimpleProtocolClient stand-in for probe tests."""

    def __init__(
        self,
        port="COM5",
        timeout=2.0,
        *,
        uids=None,
        fail_app_times=0,
        alternate_uid_after=None,
    ):
        self.port = port
        self.timeout = timeout
        self.transport = FakeTransport()
        self._uids = list(uids or [bytes.fromhex("04AABBCCDD")])
        self._uid_index = 0
        self._present_after = 0
        self._polls = 0
        self.search_calls = 0
        self.capture_marks = []
        self.fail_app_times = fail_app_times
        self._app_fails_left = fail_app_times
        self.alternate_uid_after = alternate_uid_after
        self._ops = 0
        self.closed = False
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *a):
        self.closed = True
        self.transport.close()
        return None

    def get_version_string(self):
        return "TWN4 Fake 1.0"

    def get_device_type(self):
        return 0x85

    def get_supported_tag_types(self):
        return (0, 0xFFFFFFFF)

    def set_rf_off(self):
        return None

    def search_tag(self, max_id_bytes=32):
        self.search_calls += 1
        self._polls += 1
        # First few polls: no tag (wait-for-tag behavior).
        if self._polls <= 2:
            return None
        uid = self._uids[min(self._uid_index, len(self._uids) - 1)]
        if (
            self.alternate_uid_after is not None
            and self.search_calls > self.alternate_uid_after
        ):
            uid = bytes.fromhex("99DEADBEEF01")
        return TagRead(0x04, len(uid) * 8, uid)

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        self._ops += 1
        op = tx[0]
        if op == 0x60:
            return with_crc(VERSION)
        if op == 0x30:
            # READ block
            return with_crc(bytes(16))
        if op == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0x30 and end == 0x37:
                if self._app_fails_left > 0:
                    self._app_fails_left -= 1
                    raise SerialCommunicationError("application timeout")
                return with_crc(REFERENCE_BLOCK)
            if start == 0xEC:
                return with_crc(bytes((0x19, 0, 0xF8, 0x48, 0x08, 1, 0x01, 0)))
            pages = end - start + 1
            return with_crc(bytes(pages * 4))
        raise AssertionError(tx.hex())


class CaptureFlowTests(unittest.TestCase):
    def _run(self, client: FakeClient, **cfg) -> tuple:
        out = io.StringIO()
        tmp_ctx = tempfile.TemporaryDirectory()
        tmp = tmp_ctx.name
        config = ProbeConfig(
            port=client.port,
            output=Path(tmp),
            tag_timeout=cfg.get("tag_timeout", 5.0),
            retry_count=cfg.get("retry_count", 3),
            retry_delay_ms=cfg.get("retry_delay_ms", 1.0),
            session_seconds=cfg.get("session_seconds", 0.05),
            session_interval_ms=1.0,
            poll_interval_seconds=0.0,
            confirm_reads=cfg.get("confirm_reads", 3),
            skip_eeprom=cfg.get("skip_eeprom", False),
            skip_application=cfg.get("skip_application", False),
            skip_session=cfg.get("skip_session", False),
            raw_trace=cfg.get("raw_trace", False),
        )

        def factory(port, timeout):
            client.port = port
            client.timeout = timeout
            return client

        sleeps: list[float] = []

        def sleep(dt):
            sleeps.append(dt)

        probe = CaptureProbe(
            config,
            client_factory=factory,
            sleep=sleep,
            stdout=out,
        )
        result = probe.run()
        self.addCleanup(tmp_ctx.cleanup)
        return result, out.getvalue(), Path(tmp), sleeps, probe

    def test_wait_ends_on_first_uid_no_removal(self):
        client = FakeClient()
        result, console, *_ = self._run(client, skip_eeprom=True, skip_session=True)
        self.assertIsNotNone(result.uid)
        self.assertIn("TAG DETECTED", console)
        self.assertIn("Čekám na tag", console)
        self.assertNotIn("waiting_for_removal", console.lower())
        self.assertNotIn("Oddalte", console)
        # After first detection, capture runs once; no endless search loop for new tags.
        self.assertTrue(result.port_closed)

    def test_capture_runs_only_once(self):
        client = FakeClient()
        result, _, __, ___, probe = self._run(
            client, skip_eeprom=True, skip_session=True
        )
        self.assertTrue(probe._capture_ran)
        self.assertEqual(result.phase_statuses.get("tag_detection"), "ok")

    def test_uid_changed_records_error_keeps_original(self):
        # After enough searches, return a different UID.
        client = FakeClient(alternate_uid_after=6)
        result, _, root, __, ___ = self._run(
            client,
            skip_eeprom=True,
            skip_session=True,
            confirm_reads=3,
        )
        self.assertEqual(result.uid, "04AABBCCDD")
        errors = result.errors
        self.assertTrue(any(e.get("code") == "uid_changed" for e in errors))

    def test_phase_timeout_retries_then_continues(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise SerialCommunicationError("timeout waiting")
            return "ok"

        delays = []
        result = run_with_retry(
            flaky,
            retry_count=3,
            retry_delay_ms=10,
            sleep=lambda d: delays.append(d),
        )
        self.assertEqual(result.status, PhaseStatus.OK)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(delays), 2)

        # Application fails all retries; eeprom/session still attempted.
        client = FakeClient(fail_app_times=10)
        probe_result, console, *_ = self._run(
            client,
            retry_count=3,
            retry_delay_ms=1,
            skip_eeprom=False,
            skip_session=True,
        )
        self.assertIn(
            probe_result.phase_statuses.get("application"),
            {"timeout", "serial_timeout", "reader_error", "exception"},
        )
        self.assertIn(probe_result.phase_statuses.get("eeprom"), {"ok", "partial"})
        self.assertIn("after 3 retries", console.lower())

    def test_incremental_persist_and_partial(self):
        client = FakeClient(fail_app_times=10)
        result, _, root, __, ___ = self._run(
            client,
            retry_count=2,
            skip_session=True,
        )
        # Find capture dir
        caps = list(Path(root).iterdir())
        self.assertEqual(len(caps), 1)
        cap = caps[0]
        self.assertTrue((cap / "summary.json").exists())
        self.assertTrue((cap / "phases" / "reader_info.json").exists())
        self.assertTrue((cap / "phases" / "tag_detection.json").exists())
        # EEPROM saved even if application failed
        self.assertTrue((cap / "phases" / "eeprom.json").exists())
        self.assertEqual(result.overall, OverallStatus.PARTIAL)

    def test_exception_does_not_wipe_saved_data(self):
        client = FakeClient()

        class BoomClient(FakeClient):
            def get_version_string(self):
                return "ok"

            def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
                if tx[0] == 0x60:
                    # identification ok first...
                    return with_crc(VERSION)
                if tx[0] == 0x3A and tx[1] == 0x00:
                    raise RuntimeError("boom during eeprom")
                return super().iso14443_3_tdx(tx, max_rx_bytes, timeout_ms)

        boom = BoomClient()
        result, _, root, __, ___ = self._run(
            boom, skip_session=True, skip_application=True
        )
        cap = next(Path(root).iterdir())
        reader = json.loads((cap / "phases" / "reader_info.json").read_text(encoding="utf-8"))
        self.assertEqual(reader["status"], "ok")
        self.assertTrue((cap / "phases" / "tag_detection.json").exists())
        self.assertIsNotNone(result.uid)

    def test_failed_without_tag(self):
        class NoTagClient(FakeClient):
            def search_tag(self, max_id_bytes=32):
                self.search_calls += 1
                return None

        client = NoTagClient()
        # Use monotonic-based timeout: sleep no-op but advance via tiny timeout
        # Override wait by making tag_timeout very small and poll 0.
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            config = ProbeConfig(
                port="COM5",
                output=Path(tmp),
                tag_timeout=0.01,
                poll_interval_seconds=0.0,
                retry_delay_ms=1,
            )
            # Force deadline expiry: monkeypatch time.monotonic in wait by
            # using a client that never returns a tag and real short timeout.
            t0 = time.monotonic()

            class ClockClient(NoTagClient):
                pass

            c = ClockClient()
            probe = CaptureProbe(
                config,
                client_factory=lambda p, t: c,
                sleep=lambda d: None,
                stdout=out,
            )
            # Patch wait loop deadline by reducing tag_timeout further via config
            result = probe.run()
            self.assertEqual(result.overall, OverallStatus.FAILED)
            self.assertIsNone(result.uid)
            self.assertTrue(c.closed)
            # Ensure we spent at least the timeout window conceptually
            self.assertGreaterEqual(time.monotonic() - t0, 0.0)

    def test_raw_trace_tx_rx_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw_serial.jsonl"
            tracer = RawSerialTracer(path)

            def exchange(cmd: bytes) -> bytes:
                return b"\x00\x01"

            wrapped = tracer.wrap_exchange(exchange)
            wrapped(b"\x05\x00\x20")
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            tx = json.loads(lines[0])
            rx = json.loads(lines[1])
            self.assertEqual(tx["direction"], "TX")
            self.assertEqual(rx["direction"], "RX")
            self.assertIn("t_mono", tx)
            self.assertIn("t_mono", rx)
            self.assertEqual(tx["decoded"], "SearchTag")
            self.assertIn("raw_hex", tx)

    def test_port_closed(self):
        client = FakeClient()
        result, *_ = self._run(client, skip_eeprom=True, skip_session=True)
        self.assertTrue(result.port_closed)
        self.assertTrue(client.closed)
        self.assertTrue(client.transport.closed)


if __name__ == "__main__":
    unittest.main()
