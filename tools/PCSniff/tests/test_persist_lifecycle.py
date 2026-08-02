from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import _pathsetup  # noqa: F401
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import TagRead

from twn4_capture_probe.capture import CaptureProbe, ProbeConfig
from twn4_capture_probe.raw_trace import RawSerialTracer
from twn4_capture_probe.status import PhaseStatus, classify_exception


VERSION = bytes.fromhex("00 04 04 05 02 02 13 03")
REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA"
    "FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93"
)


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class TraceAwareFakeClient:
    """Fake client that routes ops through transport.exchange for raw tracing."""

    def __init__(self, port="COM5", timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.transport = _ExchangeTransport(self)
        self.closed = False
        self.entered = False
        self._polls = 0
        self.uid = bytes.fromhex("04367F5A2D7280")
        self.exchange_log: list[bytes] = []
        self.working_dirs_during_exchange: list[str] = []
        self._store_root_fn = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *a):
        self.closed = True
        return None

    def get_version_string(self):
        self.transport.exchange(b"\x00\x04\xff")
        return "TWN4 Fake 1.0"

    def get_device_type(self):
        self.transport.exchange(b"\x00\x06")
        return 0x85

    def get_supported_tag_types(self):
        self.transport.exchange(b"\x05\x04")
        return (0, 0xFFFFFFFF)

    def set_rf_off(self):
        self.transport.exchange(b"\x05\x01")

    def search_tag(self, max_id_bytes=32):
        self.transport.exchange(b"\x05\x00" + bytes([max_id_bytes]))
        self._polls += 1
        if self._polls <= 2:
            return None
        return TagRead(0x04, len(self.uid) * 8, self.uid)

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        # Record via exchange so raw tracer sees post-tag RF ops.
        self.transport.exchange(b"\x12\x07" + bytes([len(tx)]) + tx[:1])
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


class _ExchangeTransport:
    def __init__(self, client: TraceAwareFakeClient):
        self.client = client
        self.closed = False
        self.exchange = self._exchange

    def open(self):
        return None

    def close(self):
        self.closed = True

    def _exchange(self, command: bytes) -> bytes:
        self.client.exchange_log.append(command)
        if self.client._store_root_fn is not None:
            self.client.working_dirs_during_exchange.append(
                self.client._store_root_fn()
            )
        return b"\x00"


class PersistLifecycleTests(unittest.TestCase):
    def _run(self, *, raw_trace: bool, client=None, **cfg):
        out = io.StringIO()
        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        client = client or TraceAwareFakeClient()

        def factory(port, timeout):
            client.port = port
            client.timeout = timeout
            return client

        config = ProbeConfig(
            port="COM5",
            output=Path(tmp_ctx.name),
            raw_trace=raw_trace,
            tag_timeout=5.0,
            retry_count=2,
            retry_delay_ms=1.0,
            session_seconds=0.02,
            session_interval_ms=1.0,
            poll_interval_seconds=0.0,
            confirm_reads=3,
            skip_eeprom=cfg.get("skip_eeprom", True),
            skip_application=cfg.get("skip_application", False),
            skip_session=cfg.get("skip_session", True),
        )
        probe = CaptureProbe(
            config,
            client_factory=factory,
            sleep=lambda _d: None,
            stdout=out,
        )

        # Observe working dir name while exchanges happen.
        client._store_root_fn = lambda: (
            str(probe._store.root) if probe._store else ""
        )

        pending_seen = {"value": None}

        original_announce = probe._announce_detected

        def announce_and_check():
            assert probe._store is not None
            pending_seen["value"] = probe._store.root.name
            self.assertTrue(
                probe._store.root.name.endswith("UID-pending"),
                f"dir renamed too early: {probe._store.root}",
            )
            # Tracer must still point at an existing writable path.
            if probe._tracer is not None:
                self.assertTrue(
                    probe._tracer.path.exists(),
                    f"tracer path missing: {probe._tracer.path}",
                )
                self.assertIn("UID-pending", str(probe._tracer.path))
            original_announce()

        probe._announce_detected = announce_and_check  # type: ignore[method-assign]
        result = probe.run()
        return result, out.getvalue(), Path(tmp_ctx.name), client, pending_seen

    def test_starts_in_uid_pending_and_renames_after_close(self):
        result, _, root, client, pending = self._run(raw_trace=True)
        self.assertIsNotNone(pending["value"])
        self.assertTrue(str(pending["value"]).endswith("UID-pending"))
        self.assertTrue(result.output_dir.name.endswith("UID-04367F5A2D7280"))
        self.assertFalse(result.output_dir.name.endswith("UID-pending"))
        self.assertTrue(client.closed)
        # During capture exchanges, directory must stay pending.
        self.assertTrue(client.working_dirs_during_exchange)
        self.assertTrue(
            all("UID-pending" in d for d in client.working_dirs_during_exchange),
            client.working_dirs_during_exchange[:5],
        )

    def test_raw_trace_has_post_tag_commands(self):
        result, _, __, client, ___ = self._run(raw_trace=True)
        raw_path = result.output_dir / "raw_serial.jsonl"
        self.assertTrue(raw_path.exists())
        lines = [
            json.loads(line)
            for line in raw_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        decoded = [r.get("decoded") for r in lines if r.get("direction") == "TX"]
        self.assertIn("GetVersionString", decoded)
        self.assertIn("SearchTag", decoded)
        # Post-tag RF path uses ISO14443_3_TDX
        self.assertIn("ISO14443_3_TDX", decoded)
        search_idxs = [i for i, d in enumerate(decoded) if d == "SearchTag"]
        iso_idxs = [i for i, d in enumerate(decoded) if d == "ISO14443_3_TDX"]
        self.assertTrue(search_idxs)
        self.assertTrue(iso_idxs)
        self.assertGreater(max(iso_idxs), min(search_idxs))

    def test_summary_output_dir_is_final_uid_path(self):
        result, *_ = self._run(raw_trace=True)
        summary = json.loads(
            (result.output_dir / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["uid"], "04367F5A2D7280")
        self.assertEqual(Path(summary["output_dir"]), result.output_dir)
        self.assertIn("UID-04367F5A2D7280", summary["output_dir"])
        self.assertNotIn("UID-pending", Path(summary["output_dir"]).name)

    def test_events_and_errors_consistent_after_finalize(self):
        result, *_ = self._run(raw_trace=True)
        events_path = result.output_dir / "events.jsonl"
        errors_path = result.output_dir / "errors.json"
        self.assertTrue(events_path.exists())
        self.assertTrue(errors_path.exists())
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        names = [e["event"] for e in events]
        self.assertIn("probe_started", names)
        self.assertIn("uid_locked", names)
        self.assertIn("raw_trace_closed", names)
        self.assertIn("port_closed", names)
        self.assertIn("capture_dir_renamed", names)
        # Rename must be after close events.
        self.assertGreater(
            names.index("capture_dir_renamed"),
            names.index("raw_trace_closed"),
        )
        self.assertGreater(
            names.index("capture_dir_renamed"),
            names.index("port_closed"),
        )
        errors = json.loads(errors_path.read_text(encoding="utf-8"))
        self.assertIsInstance(errors, list)
        pending_errs = [
            e
            for e in errors
            if "UID-pending" in e.get("message", "") and "raw_serial" in e.get("message", "")
        ]
        self.assertEqual(pending_errs, [])

    def test_windows_style_paths_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Use Path that stringifies with backslashes on Windows.
            base = Path(tmp)
            mixed = Path(str(base).replace("/", "\\")) if "\\" in str(base) else base
            out = io.StringIO()
            client = TraceAwareFakeClient()
            config = ProbeConfig(
                port="COM5",
                output=mixed / "windows_probe",
                raw_trace=True,
                tag_timeout=5,
                retry_count=1,
                retry_delay_ms=1,
                session_seconds=0.01,
                poll_interval_seconds=0,
                confirm_reads=1,
                skip_eeprom=True,
                skip_session=True,
            )
            result = CaptureProbe(
                config,
                client_factory=lambda p, t: client,
                sleep=lambda _d: None,
                stdout=out,
            ).run()
            self.assertTrue((result.output_dir / "raw_serial.jsonl").exists())
            self.assertIn("UID-04367F5A2D7280", result.output_dir.name)

    def test_capture_without_raw_trace(self):
        result, _, __, ___, ____ = self._run(raw_trace=False)
        self.assertTrue(result.output_dir.name.endswith("UID-04367F5A2D7280"))
        self.assertFalse((result.output_dir / "raw_serial.jsonl").exists())
        self.assertEqual(result.phase_statuses.get("tag_detection"), "ok")

    def test_raw_trace_io_error_does_not_break_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw_serial.jsonl"
            tracer = RawSerialTracer(path)
            calls = {"n": 0}

            def exchange(cmd: bytes) -> bytes:
                calls["n"] += 1
                return b"\x00\x01"

            wrapped = tracer.wrap_exchange(exchange)
            # First call OK
            wrapped(b"\x05\x00\x20")
            # Simulate mid-capture directory disappearing (UID-pending rename bug).
            tracer.path = Path(tmp) / "UID-pending-gone" / "raw_serial.jsonl"
            # Reader must still succeed even though diagnostic path is gone.
            resp = wrapped(b"\x05\x00\x20")
            self.assertEqual(resp, b"\x00\x01")
            self.assertEqual(calls["n"], 2)
            self.assertFalse(tracer.enabled)
            self.assertTrue(tracer.io_errors)

    def test_filenotfound_not_classified_as_timeout(self):
        exc = FileNotFoundError(
            2,
            "No such file or directory",
            r"C:\tmp\2026-07-31_060156_UID-pending\raw_serial.jsonl",
        )
        status = classify_exception(exc)
        self.assertEqual(status, PhaseStatus.RAW_TRACE_ERROR)
        self.assertNotEqual(status, PhaseStatus.TIMEOUT)
        self.assertNotEqual(status, PhaseStatus.SERIAL_TIMEOUT)

        from twn4_capture_probe.status import aggregate_attempt_statuses

        phase = aggregate_attempt_statuses(
            [
                PhaseStatus.RAW_TRACE_ERROR.value,
                PhaseStatus.RAW_TRACE_ERROR.value,
                PhaseStatus.READER_ERROR.value,
            ],
            success_count=0,
            required_successes=3,
        )
        self.assertEqual(phase, PhaseStatus.RAW_TRACE_ERROR)


if __name__ == "__main__":
    unittest.main()
