from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ntag import EEPROM_WATCH_SIZE_BYTES, EEPROM_WATCH_START_PAGE
from .application_capture import load_capture_directory, ndef_id_from_block
from .checksums import evaluate_checksum_candidates_multi
from .dump_loaders import parse_hex_bytes


@dataclass
class StudySample:
    sample_id: str
    uid: str | None
    get_version: str | None
    ndef_id: str | None
    label: str | None
    state: str | None
    timestamp: str | None
    block: bytes
    source_path: str
    notes: str = ""


def samples_from_captures(paths: list[Path]) -> list[StudySample]:
    samples: list[StudySample] = []
    for path in paths:
        loaded = load_capture_directory(path)
        if not loaded["valid"]:
            raise ValueError(f"Nevalidní capture: {path}")
        meta = loaded["metadata"]
        block = loaded["block"]
        samples.append(
            StudySample(
                sample_id=f"{path.name}#rep",
                uid=meta.get("uid"),
                get_version=meta.get("get_version"),
                ndef_id=meta.get("ndef_id") or ndef_id_from_block(block),
                label=meta.get("label"),
                state=meta.get("state"),
                timestamp=meta.get("finished_at") or meta.get("started_at"),
                block=block,
                source_path=str(path),
                notes=meta.get("notes") or "",
            )
        )
    return samples


def samples_from_manifest(manifest_path: Path) -> list[StudySample]:
    path = Path(manifest_path)
    if path.is_dir():
        path = path / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    records = document.get("records") or []
    samples: list[StudySample] = []
    for item in records:
        samples.append(
            StudySample(
                sample_id=item["sample_id"],
                uid=item.get("uid"),
                get_version=item.get("get_version"),
                ndef_id=item.get("ndef_id"),
                label=item.get("label"),
                state=item.get("state"),
                timestamp=item.get("timestamp"),
                block=parse_hex_bytes(item["raw_block_hex"]),
                source_path=item.get("source_path") or "",
                notes=item.get("notes") or "",
            )
        )
    return samples


def analyze_byte_positions(samples: list[StudySample]) -> list[dict[str, Any]]:
    if not samples:
        return []
    uids = {sample.uid for sample in samples}
    states = {sample.state for sample in samples}
    rows: list[dict[str, Any]] = []
    for index in range(EEPROM_WATCH_SIZE_BYTES):
        values = [sample.block[index] for sample in samples]
        by_uid: dict[str | None, set[int]] = defaultdict(set)
        by_state: dict[str | None, set[int]] = defaultdict(set)
        for sample in samples:
            by_uid[sample.uid].add(sample.block[index])
            by_state[sample.state].add(sample.block[index])
        unique_values = sorted(set(values))
        bitwise_and = 0xFF
        bitwise_or = 0x00
        for value in values:
            bitwise_and &= value
            bitwise_or |= value
        changing_mask = bitwise_and ^ bitwise_or
        # Shannon-ish entropy over observed bytes at this offset.
        counts = Counter(values)
        total = len(values)
        entropy = 0.0
        for count in counts.values():
            p = count / total
            entropy -= p * math.log2(p)

        if len(uids) > 1:
            per_uid_constants = all(len(items) == 1 for items in by_uid.values())
            distinct_uid_values = len({next(iter(items)) for items in by_uid.values()})
            varies_by_uid = per_uid_constants and distinct_uid_values > 1
        else:
            varies_by_uid = False

        if len(states) > 1:
            distinct_state_values = len(
                {next(iter(items)) for items in by_state.values() if len(items) == 1}
            )
            # state-correlated if overall values differ and labels differ
            varies_by_state = len(unique_values) > 1 and distinct_state_values > 1
            varies_over_time = any(len(items) > 1 for items in by_state.values())
        else:
            varies_by_state = False
            varies_over_time = len(unique_values) > 1 and len(uids) <= 1

        role, confidence, evidence, counter = _classify_role(
            index=index,
            unique_values=unique_values,
            varies_by_uid=varies_by_uid,
            varies_by_state=varies_by_state,
            varies_over_time=varies_over_time,
            samples=samples,
            uid_count=len(uids),
        )
        rows.append(
            {
                "index": index,
                "absolute_eeprom_offset": EEPROM_WATCH_START_PAGE * 4 + index,
                "page": EEPROM_WATCH_START_PAGE + (index // 4),
                "byte_in_page": index % 4,
                "observed_values": [f"0x{value:02X}" for value in unique_values],
                "unique_value_count": len(unique_values),
                "constant": len(unique_values) == 1,
                "varies_by_uid": varies_by_uid,
                "varies_by_state": varies_by_state,
                "varies_over_time": varies_over_time,
                "all_ff": all(value == 0xFF for value in values),
                "all_zero": all(value == 0 for value in values),
                "bitwise_and": bitwise_and,
                "bitwise_or": bitwise_or,
                "changing_bit_mask": changing_mask,
                "entropy": round(entropy, 4),
                "candidate_role": role,
                "confidence": confidence,
                "evidence": evidence,
                "counter_evidence": counter,
                "sample_count": len(samples),
            }
        )
    return rows


def _classify_role(
    *,
    index: int,
    unique_values: list[int],
    varies_by_uid: bool,
    varies_by_state: bool,
    varies_over_time: bool,
    samples: list[StudySample],
    uid_count: int,
) -> tuple[str, str, str, str]:
    if len(unique_values) == 1:
        return (
            "constant",
            "medium" if len(samples) >= 3 else "low",
            "same value across all samples",
            "single-tag datasets cannot prove model-wide constancy"
            if uid_count < 2
            else "none",
        )
    # identifier correlation on page 0x33 bytes
    if 12 <= index <= 15 and varies_by_uid:
        return (
            "identifier-correlated",
            "high" if uid_count >= 3 else ("medium" if uid_count == 2 else "low"),
            "varies by UID on page 0x33 region",
            "needs multi-tag confirmation for high confidence"
            if uid_count < 3
            else "none",
        )
    if varies_by_state and not varies_by_uid:
        return (
            "state-correlated",
            "medium" if len(samples) >= 3 else "low",
            "value set differs across stated states",
            "state labels are user metadata, not proof",
        )
    if varies_over_time:
        return (
            "time-varying",
            "low",
            "multiple values over time for same tag/state grouping",
            "insufficient evidence for semantic meaning",
        )
    return (
        "unknown",
        "low",
        "variable without clear uid/state pattern",
        "insufficient evidence",
    )


def correlate_identifier(samples: list[StudySample]) -> dict[str, Any]:
    total = 0
    le_matches = 0
    be_matches = 0
    for sample in samples:
        if not sample.ndef_id or len(sample.block) < 16:
            continue
        total += 1
        try:
            ndef = bytes.fromhex(sample.ndef_id)
        except ValueError:
            continue
        if len(ndef) != 4:
            continue
        page = sample.block[12:16]
        if page == ndef[::-1]:
            le_matches += 1
        if page == ndef:
            be_matches += 1

    if total == 0:
        return {
            "identifier_offset": 12,
            "identifier_page": 0x33,
            "byte_order": None,
            "matching_samples": 0,
            "total_samples": 0,
            "confidence": "low",
            "summary": "insufficient evidence",
        }

    if le_matches == total and total >= 3:
        confidence = "high"
        order = "little-endian"
        summary = "confirmed structural match across multiple tags/samples"
    elif le_matches == total and total == 2:
        confidence = "medium"
        order = "little-endian"
        summary = "repeatable correlation (little-endian)"
    elif le_matches == total:
        confidence = "low"
        order = "little-endian"
        summary = "observed correlation on single-tag/sample set"
    elif be_matches == total and total >= 2:
        confidence = "medium"
        order = "big-endian"
        summary = "repeatable correlation (big-endian)"
    else:
        confidence = "low"
        order = "little-endian" if le_matches >= be_matches else "big-endian"
        summary = "insufficient evidence / partial match"

    return {
        "identifier_offset": 12,
        "identifier_page": 0x33,
        "byte_order": order,
        "matching_samples": max(le_matches, be_matches),
        "le_matches": le_matches,
        "be_matches": be_matches,
        "total_samples": total,
        "confidence": confidence,
        "summary": summary,
    }


def find_counter_timestamp_candidates(
    samples: list[StudySample],
) -> dict[str, list[dict[str, Any]]]:
    """Intra-tag heuristics on ordered samples (by timestamp if available)."""
    by_uid: dict[str, list[StudySample]] = defaultdict(list)
    for sample in samples:
        if sample.uid:
            by_uid[sample.uid].append(sample)

    counters: list[dict[str, Any]] = []
    timestamps: list[dict[str, Any]] = []

    for uid, group in by_uid.items():
        ordered = sorted(group, key=lambda item: item.timestamp or item.sample_id)
        if len(ordered) < 2:
            continue
        blocks = [item.block for item in ordered]

        for width, step in ((1, 1), (2, 2), (4, 4)):
            for offset in range(0, EEPROM_WATCH_SIZE_BYTES - width + 1, step):
                for endian in ("little", "big"):
                    if width == 1 and endian == "big":
                        continue
                    series = [
                        int.from_bytes(block[offset : offset + width], endian)
                        for block in blocks
                    ]
                    if len(set(series)) <= 1:
                        continue
                    deltas = [b - a for a, b in zip(series, series[1:])]
                    mono_inc = all(delta > 0 for delta in deltas)
                    mono_dec = all(delta < 0 for delta in deltas)
                    step1 = all(delta == 1 for delta in deltas)
                    const_step = len(set(deltas)) == 1
                    wrap = any(delta < 0 for delta in deltas) and any(
                        delta > 0 for delta in deltas
                    )
                    if mono_inc or mono_dec or wrap:
                        counters.append(
                            {
                                "uid": uid,
                                "offset": offset,
                                "width": width * 8,
                                "endian": endian,
                                "values": series,
                                "deltas": deltas,
                                "monotonic_increase": mono_inc,
                                "monotonic_decrease": mono_dec,
                                "step_one": step1,
                                "constant_step": const_step,
                                "wrap_around_candidate": wrap,
                                "confidence": "medium"
                                if (step1 or const_step) and len(series) >= 3
                                else "low",
                                "note": "possible-counter candidate — not confirmed",
                            }
                        )
                    if width == 4 and mono_inc:
                        if all(1_500_000_000 <= value <= 2_200_000_000 for value in series):
                            timestamps.append(
                                {
                                    "uid": uid,
                                    "offset": offset,
                                    "endian": endian,
                                    "values": series,
                                    "hypothesis": "unix-seconds-like range",
                                    "confidence": "low",
                                    "note": "timestamp-like numeric range only — insufficient evidence",
                                }
                            )
    return {"counter_candidates": counters, "timestamp_candidates": timestamps}


def compare_captures(
    paths: list[Path],
    *,
    mode: str,
) -> dict[str, Any]:
    samples = samples_from_captures(paths)
    if mode == "intra-tag":
        uids = {sample.uid for sample in samples}
        if len(uids) != 1 or None in uids:
            raise ValueError(
                "intra-tag mode requires exactly one UID across captures; "
                f"found {sorted(uids)}"
            )
    elif mode == "inter-tag":
        uids = {sample.uid for sample in samples}
        if len(uids) < 2:
            raise ValueError("inter-tag mode requires at least two distinct UIDs.")
    else:
        raise ValueError("mode must be intra-tag or inter-tag")

    return _compare_samples(samples, mode=mode)


def compare_dataset(dataset_dir: Path, *, mode: str) -> dict[str, Any]:
    samples = samples_from_manifest(Path(dataset_dir))
    if not samples:
        raise ValueError("Dataset neobsahuje žádné záznamy.")
    if mode == "intra-tag":
        # pick the UID with most samples if multiple; require single UID filter ideally
        counts = Counter(sample.uid for sample in samples)
        top_uid, _ = counts.most_common(1)[0]
        samples = [sample for sample in samples if sample.uid == top_uid]
        if len(samples) < 2:
            raise ValueError("intra-tag dataset compare needs >=2 samples for one UID.")
    elif mode == "inter-tag":
        if len({sample.uid for sample in samples}) < 2:
            raise ValueError("inter-tag mode requires at least two distinct UIDs.")
    else:
        raise ValueError("mode must be intra-tag or inter-tag")
    return _compare_samples(samples, mode=mode)


def _compare_samples(samples: list[StudySample], *, mode: str) -> dict[str, Any]:
    blocks = [sample.block for sample in samples]
    constant = []
    variable = []
    byte_changes = []
    for offset in range(EEPROM_WATCH_SIZE_BYTES):
        values = [block[offset] for block in blocks]
        if len(set(values)) == 1:
            constant.append(offset)
        else:
            variable.append(offset)
            byte_changes.append(
                {
                    "absolute_offset": offset,
                    "page": EEPROM_WATCH_START_PAGE + (offset // 4),
                    "byte_in_page": offset % 4,
                    "first": values[0],
                    "last": values[-1],
                    "change_count": sum(
                        1 for a, b in zip(values, values[1:]) if a != b
                    ),
                    "values_hex": [f"0x{value:02X}" for value in values],
                    "bit_change_mask": _bit_change_mask(values),
                }
            )

    page_changes = {}
    for page in range(EEPROM_WATCH_START_PAGE, EEPROM_WATCH_START_PAGE + 8):
        base = (page - EEPROM_WATCH_START_PAGE) * 4
        page_changes[f"0x{page:02X}"] = [
            offset for offset in variable if base <= offset < base + 4
        ]

    word16 = []
    word32 = []
    for offset in range(0, EEPROM_WATCH_SIZE_BYTES - 1, 2):
        series = [
            int.from_bytes(block[offset : offset + 2], "little") for block in blocks
        ]
        if len(set(series)) > 1:
            word16.append({"offset": offset, "endian": "little", "values": series})
    for offset in range(0, EEPROM_WATCH_SIZE_BYTES - 3, 4):
        series = [
            int.from_bytes(block[offset : offset + 4], "little") for block in blocks
        ]
        if len(set(series)) > 1:
            word32.append({"offset": offset, "endian": "little", "values": series})

    positions = analyze_byte_positions(samples)
    identifier = correlate_identifier(samples)
    heuristics = find_counter_timestamp_candidates(samples)
    checksum = evaluate_checksum_candidates_multi(blocks)

    state_labels = sorted({sample.state for sample in samples if sample.state})
    report = {
        "schema_version": 1,
        "mode": mode,
        "sample_count": len(samples),
        "uids": sorted({sample.uid for sample in samples if sample.uid}),
        "states": state_labels,
        "labels": sorted({sample.label for sample in samples if sample.label}),
        "sources": [sample.source_path for sample in samples],
        "constant_offsets": constant,
        "variable_offsets": variable,
        "page_changes": page_changes,
        "byte_changes": byte_changes,
        "u16_changes": word16,
        "u32_changes": word32,
        "byte_positions": positions,
        "identifier_correlation": identifier,
        "counter_candidates": heuristics["counter_candidates"],
        "timestamp_candidates": heuristics["timestamp_candidates"],
        "checksum": {
            "total_distinct_blocks": checksum["total_distinct_blocks"],
            "top_candidates": [
                item
                for item in checksum["candidates"]
                if item["matching_samples"] > 0
            ][:20],
        },
        "summary": _summary_text(
            mode, samples, constant, variable, identifier, positions
        ),
    }
    return report


def _bit_change_mask(values: list[int]) -> int:
    and_v = 0xFF
    or_v = 0x00
    for value in values:
        and_v &= value
        or_v |= value
    return and_v ^ or_v


def _summary_text(
    mode: str,
    samples: list[StudySample],
    constant: list[int],
    variable: list[int],
    identifier: dict[str, Any],
    positions: list[dict[str, Any]],
) -> str:
    lines = [
        f"Application block {mode} comparison",
        "=================================",
        "",
        f"Samples: {len(samples)}",
        f"UIDs: {sorted({sample.uid for sample in samples})}",
        f"Constant offsets: {len(constant)}",
        f"Variable offsets: {len(variable)}",
        f"Identifier: {identifier.get('summary')} "
        f"(confidence={identifier.get('confidence')})",
        "",
        "Candidate roles (nonzero entropy / non-constant):",
    ]
    for row in positions:
        if row["constant"]:
            continue
        lines.append(
            f"  @{row['index']} page 0x{row['page']:02X}[{row['byte_in_page']}] "
            f"{row['candidate_role']} ({row['confidence']})"
        )
    lines.append("")
    lines.append(
        "Language: associations/candidates only; not confirmed field meanings "
        "unless multi-tag structural match."
    )
    lines.append("")
    return "\n".join(lines)


def comparison_to_text(report: dict[str, Any]) -> str:
    return report.get("summary") or json.dumps(report, indent=2)
