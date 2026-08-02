from __future__ import annotations

import unittest

import _pathsetup  # noqa: F401
from twn4_capture_probe.status import (
    OverallStatus,
    PhaseStatus,
    aggregate_attempt_statuses,
    classify_exception,
    compute_overall,
)


class StatusTests(unittest.TestCase):
    def test_success(self):
        phases = {
            "reader_info": PhaseStatus.OK.value,
            "tag_detection": PhaseStatus.OK.value,
            "uid_confirm": PhaseStatus.OK.value,
            "identification": PhaseStatus.OK.value,
            "eeprom": PhaseStatus.OK.value,
            "application": PhaseStatus.OK.value,
            "session": PhaseStatus.SKIPPED.value,
            "verification": PhaseStatus.OK.value,
        }
        self.assertEqual(
            compute_overall(phases, uid="04AA", usable_data=True),
            OverallStatus.SUCCESS,
        )

    def test_partial_on_unsupported_or_failed(self):
        phases = {
            "reader_info": PhaseStatus.OK.value,
            "tag_detection": PhaseStatus.OK.value,
            "uid_confirm": PhaseStatus.OK.value,
            "identification": PhaseStatus.OK.value,
            "eeprom": PhaseStatus.UNSUPPORTED.value,
            "application": PhaseStatus.SERIAL_TIMEOUT.value,
            "session": PhaseStatus.OK.value,
            "verification": PhaseStatus.OK.value,
        }
        self.assertEqual(
            compute_overall(phases, uid="04AA", usable_data=True),
            OverallStatus.PARTIAL,
        )

    def test_failed_without_results(self):
        phases = {
            "reader_info": PhaseStatus.READER_ERROR.value,
            "tag_detection": PhaseStatus.TIMEOUT.value,
        }
        self.assertEqual(
            compute_overall(phases, uid=None, usable_data=False),
            OverallStatus.FAILED,
        )

    def test_filenotfound_is_persistence_or_raw_trace(self):
        self.assertEqual(
            classify_exception(FileNotFoundError("raw_serial.jsonl missing")),
            PhaseStatus.RAW_TRACE_ERROR,
        )
        self.assertEqual(
            classify_exception(FileNotFoundError("phases/foo.json")),
            PhaseStatus.PERSISTENCE_ERROR,
        )

    def test_aggregate_does_not_invent_timeout(self):
        status = aggregate_attempt_statuses(
            ["reader_error", "reader_error", "reader_error"],
            success_count=0,
            required_successes=3,
        )
        self.assertEqual(status, PhaseStatus.READER_ERROR)


if __name__ == "__main__":
    unittest.main()
