from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elatec_uid_tool.analysis.application_capture import (
    ApplicationBlockCapture,
    CaptureConfig,
    load_capture_directory,
)
from elatec_uid_tool.analysis.application_dataset import (
    DatasetBuildConfig,
    build_application_dataset,
    write_study_plan,
)
from elatec_uid_tool.analysis.application_study import (
    StudySample,
    compare_captures,
    correlate_identifier,
    find_counter_timestamp_candidates,
)
from elatec_uid_tool.analysis.checksums import (
    crc8,
    evaluate_checksum_candidates,
    evaluate_checksum_candidates_multi,
)
from elatec_uid_tool.cli import build_parser
from elatec_uid_tool.ntag import crc_a
from elatec_uid_tool.protocol import SerialCommunicationError, TagRead


REFERENCE_BLOCK = bytes.fromhex(
    "A0 81 FF FF"
    "FF FF FF FF"
    "FF FF FF FF"
    "C9 D0 2C AA"
    "FF 3A 10 00"
    "00 33 00 02"
    "01 0D 02 02"
    "D5 01 6C 93"
)


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class ScriptedAppClient:
    def __init__(self, blocks: list[bytes] | None = None, fail_at: int | None = None):
        self.blocks = list(blocks or [REFERENCE_BLOCK, REFERENCE_BLOCK, REFERENCE_BLOCK])
        self.fail_at = fail_at
        self._index = 0
        self.write_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def search_tag(self, max_id_bytes: int = 32):
        return TagRead(0x04, 56, bytes.fromhex("04367F5A2D7280"))

    def set_rf_off(self) -> None:
        return None

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        opcode = tx[0]
        if opcode == 0x60:
            return with_crc(bytes.fromhex("00 04 04 05 02 02 13 03"))
        if opcode == 0x3A:
            start, end = tx[1], tx[2]
            if start == 0x30 and end == 0x37:
                if self.fail_at is not None and self._index == self.fail_at:
                    self._index += 1
                    raise SerialCommunicationError("simulated timeout")
                block = self.blocks[min(self._index, len(self.blocks) - 1)]
                self._index += 1
                return with_crc(block)
            # full dump chunks
            page_count = end - start + 1
            return with_crc(bytes(page_count * 4))
        if opcode in (0xA2, 0xA6, 0xA0, 0x1B):
            self.write_calls += 1
            raise AssertionError("Write opcode is forbidden")
        raise AssertionError(f"Unexpected TX {tx.hex(' ').upper()}")


def _write_fake_capture(
    root: Path,
    *,
    name: str,
    uid: str,
    block: bytes,
    label: str,
    state: str,
    stable: bool = True,
) -> Path:
    path = root / name
    path.mkdir(parents=True)
    meta = {
        "schema_version": 1,
        "uid": uid,
        "get_version": "00 04 04 05 02 02 13 03",
        "ndef_id": block[12:16][::-1].hex().upper(),
        "label": label,
        "state": state,
        "notes": "test",
        "stable_across_samples": stable,
        "read_only": True,
        "source_type": "physical_tag",
        "started_at": "t0",
        "finished_at": "t1",
    }
    (path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (path / "application_block.bin").write_bytes(block)
    sample = {
        "sample_index": 1,
        "ok": True,
        "timestamp": "t0",
        "raw_hex": block.hex(" ").upper(),
    }
    (path / "samples.jsonl").write_text(json.dumps(sample) + "\n", encoding="utf-8")
    return path


class ApplicationStudyTests(unittest.TestCase):
    def test_cli_new_commands(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "capture-application-block",
                "--port",
                "COM6",
                "--label",
                "reference-before-rf",
                "--state",
                "before-rf",
            ]
        )
        self.assertEqual(args.samples, 3)
        self.assertEqual(args.interval_ms, 250.0)
        args2 = parser.parse_args(
            [
                "build-application-dataset",
                "captures/application-block",
                "--output",
                "out",
                "--representative-only",
            ]
        )
        self.assertTrue(args2.representative_only)
        args3 = parser.parse_args(
            [
                "compare-application-captures",
                "a",
                "b",
                "--mode",
                "intra-tag",
            ]
        )
        self.assertEqual(args3.mode, "intra-tag")
        args4 = parser.parse_args(
            [
                "application-study-plan",
                "--name",
                "demo",
                "--output",
                "plan",
            ]
        )
        self.assertEqual(args4.name, "demo")

    def test_capture_stable_identical_samples(self):
        client = ScriptedAppClient([REFERENCE_BLOCK] * 3)
        with tempfile.TemporaryDirectory() as tmp:
            config = CaptureConfig(
                port="COM6",
                label="reference-before-rf",
                state="before-rf",
                notes="unit",
                samples=3,
                interval_ms=1,
                output_dir=Path(tmp),
            )
            result = ApplicationBlockCapture(
                config,
                client_factory=lambda p, t: client,
                sleep=lambda s: None,
            ).run()
            self.assertTrue(result.metadata["stable_across_samples"])
            self.assertEqual(result.metadata["successful_samples"], 3)
            self.assertEqual(result.metadata["label"], "reference-before-rf")
            self.assertEqual(result.metadata["state"], "before-rf")
            self.assertTrue((result.directory / "application_block.bin").exists())
            self.assertTrue((result.directory / "metadata.json").exists())
            self.assertEqual(client.write_calls, 0)

    def test_capture_unstable_when_sample_differs(self):
        other = bytearray(REFERENCE_BLOCK)
        other[20] = 0x44
        client = ScriptedAppClient([REFERENCE_BLOCK, bytes(other), REFERENCE_BLOCK])
        with tempfile.TemporaryDirectory() as tmp:
            result = ApplicationBlockCapture(
                CaptureConfig(
                    port="COM6",
                    label="unstable",
                    samples=3,
                    interval_ms=1,
                    output_dir=Path(tmp),
                ),
                client_factory=lambda p, t: client,
                sleep=lambda s: None,
            ).run()
            self.assertFalse(result.metadata["stable_across_samples"])
            self.assertEqual(result.metadata["unique_block_values"], 2)

    def test_capture_partial_failure(self):
        client = ScriptedAppClient(fail_at=1)
        with tempfile.TemporaryDirectory() as tmp:
            result = ApplicationBlockCapture(
                CaptureConfig(
                    port="COM6",
                    label="partial",
                    samples=3,
                    interval_ms=1,
                    output_dir=Path(tmp),
                ),
                client_factory=lambda p, t: client,
                sleep=lambda s: None,
            ).run()
            self.assertEqual(result.metadata["failed_samples"], 1)
            self.assertTrue((result.directory / "errors.jsonl").exists())

    def test_capture_optional_full_dump(self):
        client = ScriptedAppClient([REFERENCE_BLOCK])
        with tempfile.TemporaryDirectory() as tmp:
            result = ApplicationBlockCapture(
                CaptureConfig(
                    port="COM6",
                    label="full",
                    samples=1,
                    interval_ms=1,
                    output_dir=Path(tmp),
                    include_full_dump=True,
                ),
                client_factory=lambda p, t: client,
                sleep=lambda s: None,
            ).run()
            self.assertTrue((result.directory / "full_dump.bin").exists())

    def test_dataset_build_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "captures"
            other = bytearray(REFERENCE_BLOCK)
            other[12:16] = bytes.fromhex("11 22 33 44")
            _write_fake_capture(
                root,
                name="c1",
                uid="04367F5A2D7280",
                block=REFERENCE_BLOCK,
                label="reference-baseline",
                state="baseline-idle",
            )
            _write_fake_capture(
                root,
                name="c2",
                uid="AABBCCDDEEFF00",
                block=bytes(other),
                label="tag02",
                state="baseline-idle",
            )
            # invalid capture
            bad = root / "bad"
            bad.mkdir()
            (bad / "metadata.json").write_text("{}", encoding="utf-8")

            out = Path(tmp) / "dataset"
            result = build_application_dataset(
                DatasetBuildConfig(
                    input_dir=root,
                    output_dir=out,
                    representative_only=True,
                )
            )
            self.assertEqual(result.manifest["counts"]["records"], 2)
            self.assertTrue(any("invalid" in w.lower() or "Skipping" in w for w in result.warnings))
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "samples.csv").exists())

            filtered = build_application_dataset(
                DatasetBuildConfig(
                    input_dir=root,
                    output_dir=Path(tmp) / "dataset2",
                    representative_only=True,
                    uid_filter="04367F5A2D7280",
                )
            )
            self.assertEqual(filtered.manifest["counts"]["records"], 1)

    def test_intra_tag_uid_mismatch_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _write_fake_capture(
                root,
                name="a",
                uid="11111111111111",
                block=REFERENCE_BLOCK,
                label="a",
                state="before-rf",
            )
            other = bytearray(REFERENCE_BLOCK)
            other[20] = 1
            b = _write_fake_capture(
                root,
                name="b",
                uid="22222222222222",
                block=bytes(other),
                label="b",
                state="after-rf",
            )
            with self.assertRaises(ValueError):
                compare_captures([a, b], mode="intra-tag")

    def test_intra_tag_constant_and_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b1 = bytearray(REFERENCE_BLOCK)
            b2 = bytearray(REFERENCE_BLOCK)
            b2[20] = b1[20] + 1
            a = _write_fake_capture(
                root,
                name="before",
                uid="04367F5A2D7280",
                block=bytes(b1),
                label="before",
                state="before-rf",
            )
            b = _write_fake_capture(
                root,
                name="after",
                uid="04367F5A2D7280",
                block=bytes(b2),
                label="after",
                state="after-rf",
            )
            report = compare_captures([a, b], mode="intra-tag")
            self.assertEqual(report["mode"], "intra-tag")
            self.assertIn(20, report["variable_offsets"])
            self.assertNotIn(12, report["variable_offsets"])
            self.assertTrue(any(item.get("bit_change_mask", 0) for item in report["byte_changes"]))

        samples = [
            StudySample(
                sample_id="1",
                uid="U1",
                get_version=None,
                ndef_id="AA2CD0C9",
                label="t0",
                state="s0",
                timestamp="1",
                block=bytes(b1),
                source_path="x",
            ),
            StudySample(
                sample_id="2",
                uid="U1",
                get_version=None,
                ndef_id="AA2CD0C9",
                label="t1",
                state="s1",
                timestamp="2",
                block=bytes(b2),
                source_path="y",
            ),
        ]
        heur = find_counter_timestamp_candidates(samples)
        self.assertTrue(isinstance(heur["counter_candidates"], list))

    def test_identifier_correlation_multi_tag(self):
        blocks = []
        samples = []
        for index, ndef in enumerate(("AA2CD0C9", "11223344", "55667788")):
            block = bytearray(REFERENCE_BLOCK)
            raw = bytes.fromhex(ndef)
            block[12:16] = raw[::-1]
            blocks.append(bytes(block))
            samples.append(
                StudySample(
                    sample_id=str(index),
                    uid=f"UID{index}",
                    get_version="00 04 04 05 02 02 13 03",
                    ndef_id=ndef,
                    label=f"tag{index}",
                    state="baseline-idle",
                    timestamp=str(index),
                    block=bytes(block),
                    source_path=str(index),
                )
            )
        corr = correlate_identifier(samples)
        self.assertEqual(corr["matching_samples"], 3)
        self.assertEqual(corr["byte_order"], "little-endian")
        self.assertEqual(corr["confidence"], "high")

    def test_checksum_known_and_multi(self):
        payload = bytes(range(31))
        check = crc8(payload, poly=0x07, init=0x00)
        block = bytearray(32)
        block[:31] = payload
        block[31] = check
        singles = evaluate_checksum_candidates(bytes(block))
        self.assertTrue(any(item.matches and item.algorithm == "crc8-atm" for item in singles))

        other = bytearray(block)
        other[0] ^= 0x11
        other[31] = crc8(bytes(other[:31]), poly=0x07, init=0x00)
        multi = evaluate_checksum_candidates_multi([bytes(block), bytes(other)])
        atm = [
            item
            for item in multi["candidates"]
            if item["algorithm"] == "crc8-atm"
            and item["coverage"] == "payload[0:31]"
            and item["storage"] == "u8@31"
        ]
        self.assertTrue(atm)
        self.assertEqual(atm[0]["matching_samples"], 2)
        self.assertIn(atm[0]["confidence"], {"medium", "high"})

        # single-block-only match gets low confidence
        lone = evaluate_checksum_candidates_multi([REFERENCE_BLOCK])
        matched = [item for item in lone["candidates"] if item["matching_samples"] > 0]
        for item in matched:
            self.assertEqual(item["confidence"], "low")

    def test_study_plan_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_study_plan(
                name="vusion-reference-study",
                output_dir=Path(tmp) / "study",
                port="COM6",
            )
            self.assertTrue((path / "README.txt").exists())
            self.assertTrue((path / "capture_commands.txt").exists())
            self.assertTrue((path / "study.json").exists())
            text = (path / "capture_commands.txt").read_text(encoding="utf-8")
            self.assertIn("capture-application-block", text)
            self.assertIn("COM6", text)

    def test_load_capture_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_fake_capture(
                Path(tmp),
                name="cap",
                uid="04367F5A2D7280",
                block=REFERENCE_BLOCK,
                label="x",
                state="y",
            )
            loaded = load_capture_directory(path)
            self.assertTrue(loaded["valid"])
            self.assertEqual(loaded["block"], REFERENCE_BLOCK)


if __name__ == "__main__":
    unittest.main()
