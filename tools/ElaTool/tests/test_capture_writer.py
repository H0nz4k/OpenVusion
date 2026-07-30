import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.capture.models import CaptureEvent
from elatec_uid_tool.capture.writer import CaptureWriter, create_capture_dir


class CaptureWriterTests(unittest.TestCase):
    def test_create_capture_dir_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = create_capture_dir(root, "04367F5A2D7280")
            self.assertTrue(directory.exists())
            self.assertIn("04367F5A2D7280", directory.name)

            with CaptureWriter(directory) as writer:
                event = CaptureEvent(
                    seq=1,
                    t_mono_ns=100,
                    elapsed_us=0,
                    wall_time="2026-07-31T00:00:00+02:00",
                    event_type="capture_started",
                    uid="04367F5A2D7280",
                )
                writer.write_event(event)
                writer.write_metadata({"schema": 1, "uid": "04367F5A2D7280"})
                writer.write_report("ok\n")

            lines = directory.joinpath("timeline.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["event_type"], "capture_started")
            self.assertEqual(payload["seq"], 1)
            self.assertTrue(directory.joinpath("samples.csv").exists())
            self.assertTrue(directory.joinpath("metadata.json").exists())
            self.assertTrue(directory.joinpath("report.txt").exists())

    def test_errors_jsonl_on_rf_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = create_capture_dir(Path(tmp), "TEST")
            with CaptureWriter(directory) as writer:
                writer.write_event(
                    CaptureEvent(
                        seq=1,
                        t_mono_ns=1,
                        elapsed_us=0,
                        wall_time="t",
                        event_type="rf_error",
                        error="NAK",
                    )
                )
            errors = directory.joinpath("errors.jsonl").read_text(encoding="utf-8")
            self.assertIn("NAK", errors)


if __name__ == "__main__":
    unittest.main()
