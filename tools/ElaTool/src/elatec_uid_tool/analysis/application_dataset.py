from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..ntag import EEPROM_WATCH_START_PAGE
from .application_capture import block_pages_dict, load_capture_directory, ndef_id_from_block
from .checksums import evaluate_checksum_candidates_multi


@dataclass
class DatasetBuildConfig:
    input_dir: Path
    output_dir: Path
    representative_only: bool = False
    uid_filter: str | None = None
    state_filter: str | None = None
    label_filter: str | None = None


@dataclass
class DatasetBuildResult:
    directory: Path
    manifest: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def discover_capture_dirs(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    if (root / "metadata.json").exists():
        return [root]
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "metadata.json").exists()
    )


def _matches_filters(
    metadata: dict[str, Any],
    *,
    uid_filter: str | None,
    state_filter: str | None,
    label_filter: str | None,
) -> bool:
    if uid_filter and str(metadata.get("uid") or "").upper() != uid_filter.upper():
        return False
    if state_filter and str(metadata.get("state") or "") != state_filter:
        return False
    if label_filter and str(metadata.get("label") or "") != label_filter:
        return False
    return True


def build_application_dataset(config: DatasetBuildConfig) -> DatasetBuildResult:
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    capture_dirs = discover_capture_dirs(config.input_dir)
    if not capture_dirs:
        warnings.append(f"No capture directories found under {config.input_dir}")

    seen_ids: set[str] = set()
    for capture_path in capture_dirs:
        loaded = load_capture_directory(capture_path)
        metadata = loaded["metadata"]
        if not loaded["valid"]:
            warnings.append(
                f"Skipping invalid/incomplete capture: {capture_path} "
                f"({loaded.get('warning')})"
            )
            continue
        if not _matches_filters(
            metadata,
            uid_filter=config.uid_filter,
            state_filter=config.state_filter,
            label_filter=config.label_filter,
        ):
            continue

        capture_id = capture_path.name
        block = loaded["block"]
        samples = [item for item in loaded["samples"] if item.get("ok")]
        if config.representative_only or not samples:
            sample_items = [
                {
                    "sample_index": 0,
                    "raw_hex": block.hex(" ").upper(),
                    "timestamp": metadata.get("finished_at")
                    or metadata.get("started_at"),
                    "representative": True,
                }
            ]
        else:
            sample_items = []
            for item in samples:
                from .dump_loaders import parse_hex_bytes

                sample_items.append(
                    {
                        "sample_index": item.get("sample_index"),
                        "raw_hex": item.get("raw_hex"),
                        "timestamp": item.get("timestamp"),
                        "block": parse_hex_bytes(item["raw_hex"]),
                        "representative": False,
                    }
                )

        for item in sample_items:
            if "block" in item:
                sample_block = item["block"]
            else:
                sample_block = block
            sample_id = f"{capture_id}#{item.get('sample_index', 0)}"
            if sample_id in seen_ids:
                warnings.append(f"Duplicate sample_id rewritten: {sample_id}")
                suffix = 1
                while f"{sample_id}_{suffix}" in seen_ids:
                    suffix += 1
                sample_id = f"{sample_id}_{suffix}"
            seen_ids.add(sample_id)
            pages = block_pages_dict(sample_block)
            records.append(
                {
                    "sample_id": sample_id,
                    "capture_id": capture_id,
                    "uid": metadata.get("uid"),
                    "get_version": metadata.get("get_version"),
                    "ndef_id": metadata.get("ndef_id")
                    or ndef_id_from_block(sample_block),
                    "label": metadata.get("label"),
                    "state": metadata.get("state"),
                    "timestamp": item.get("timestamp"),
                    "raw_block_hex": sample_block.hex(" ").upper(),
                    **{
                        f"page_{page:02x}": pages[f"0x{page:02X}"]
                        for page in range(
                            EEPROM_WATCH_START_PAGE, EEPROM_WATCH_START_PAGE + 8
                        )
                    },
                    "identifier_le": sample_block[12:16].hex(" ").upper(),
                    "stable_capture": bool(metadata.get("stable_across_samples")),
                    "source_path": str(capture_path),
                    "notes": metadata.get("notes") or "",
                }
            )

    output = Path(config.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    unique_blocks = {item["raw_block_hex"] for item in records}
    uids = sorted({item["uid"] for item in records if item.get("uid")})
    states = sorted({item["state"] for item in records if item.get("state")})
    labels = sorted({item["label"] for item in records if item.get("label")})
    captures = sorted({item["capture_id"] for item in records})

    blocks_for_checksum = []
    for hex_value in sorted(unique_blocks):
        from .dump_loaders import parse_hex_bytes

        blocks_for_checksum.append(parse_hex_bytes(hex_value))
    checksum = evaluate_checksum_candidates_multi(blocks_for_checksum)

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "input_dir": str(config.input_dir),
        "representative_only": config.representative_only,
        "filters": {
            "uid": config.uid_filter,
            "state": config.state_filter,
            "label": config.label_filter,
        },
        "counts": {
            "records": len(records),
            "captures": len(captures),
            "uids": len(uids),
            "states": len(states),
            "labels": len(labels),
            "unique_blocks": len(unique_blocks),
        },
        "uids": uids,
        "states": states,
        "labels": labels,
        "captures": captures,
        "warnings": warnings,
        "records": records,
    }

    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output / "blocks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for item in records:
            handle.write(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    fieldnames = [
        "sample_id",
        "capture_id",
        "uid",
        "get_version",
        "ndef_id",
        "label",
        "state",
        "timestamp",
        "raw_block_hex",
        *[f"page_{page:02x}" for page in range(0x30, 0x38)],
        "identifier_le",
        "stable_capture",
        "source_path",
        "notes",
    ]
    with (output / "samples.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in records:
            writer.writerow(item)

    (output / "checksum_candidates.json").write_text(
        json.dumps(checksum, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output / "checksum_candidates.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "algorithm",
                "coverage",
                "storage",
                "matching_samples",
                "total_samples",
                "confidence",
                "note",
            ],
        )
        writer.writeheader()
        for item in checksum.get("candidates", []):
            writer.writerow(item)

    (output / "checksum_report.txt").write_text(
        checksum.get("report_text", ""),
        encoding="utf-8",
    )
    report = _dataset_report(manifest, checksum)
    (output / "dataset_report.txt").write_text(report, encoding="utf-8")

    return DatasetBuildResult(directory=output, manifest=manifest, warnings=warnings)


def _dataset_report(manifest: dict[str, Any], checksum: dict[str, Any]) -> str:
    counts = manifest["counts"]
    lines = [
        "Application Block Dataset Report",
        "================================",
        "",
        f"Captures: {counts['captures']}",
        f"UIDs: {counts['uids']}",
        f"States: {counts['states']}",
        f"Labels: {counts['labels']}",
        f"Valid records: {counts['records']}",
        f"Unique blocks: {counts['unique_blocks']}",
        "",
        "UIDs: " + ", ".join(manifest.get("uids") or []) ,
        "States: " + ", ".join(manifest.get("states") or []),
        "",
        "Checksum candidates with matches across samples:",
    ]
    matches = [
        item
        for item in checksum.get("candidates", [])
        if item.get("matching_samples", 0) > 0
    ]
    if not matches:
        lines.append("  (none — insufficient evidence)")
    else:
        for item in matches[:20]:
            lines.append(
                f"  - {item['algorithm']} {item['coverage']} "
                f"{item['matching_samples']}/{item['total_samples']} "
                f"confidence={item['confidence']}"
            )
    if manifest.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for warning in manifest["warnings"]:
            lines.append(f"  - {warning}")
    lines.append("")
    lines.append(
        "Limitations: labels/states are user metadata; roles are candidates only."
    )
    lines.append(
        "Recommended next samples: more UIDs of same model; before/after display update."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_study_plan(
    *,
    name: str,
    output_dir: Path,
    port: str = "COM6",
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    study = {
        "schema_version": 1,
        "name": name,
        "read_only": True,
        "created_at": datetime.now().astimezone().isoformat(),
        "port_hint": port,
        "phases": [
            "baseline-idle capture",
            "session monitor (logic-analyzer session-only)",
            "after-session-monitor capture",
            "trigger-analysis --all",
            "after-trigger-analysis capture",
            "optional display-update captures",
            "repeat on additional same-model tags",
            "build-application-dataset + compare-application-dataset",
        ],
    }
    (output / "study.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = f"""Application Block Study: {name}
====================================

READ-ONLY experiment. Do not WRITE to the tag.

Manual procedure
----------------
1. Place the reference tag on the reader ({port}).
2. Capture baseline:
   python -m elatec_uid_tool capture-application-block --port {port} --label reference-baseline --state baseline-idle
3. Optional session monitor:
   python -m elatec_uid_tool logic-analyzer --port {port} --duration 5 --session-only --verbose
4. Capture after session monitor:
   python -m elatec_uid_tool capture-application-block --port {port} --label reference-after-session --state after-session-monitor
5. Run trigger analysis (RF association study; no EEPROM write):
   python -m elatec_uid_tool trigger-analysis --port {port} --all --verbose
6. Capture after trigger analysis:
   python -m elatec_uid_tool capture-application-block --port {port} --label reference-after-trigger --state after-trigger-analysis
7. If the display content changes, capture before/after-display-update.
8. Repeat captures with other same-model tags (different UID / NDEF ID).
9. Build dataset and compare:
   python -m elatec_uid_tool build-application-dataset captures/application-block --output captures/application-datasets/{name} --representative-only
   python -m elatec_uid_tool compare-application-dataset captures/application-datasets/{name} --mode inter-tag

Trigger Analysis conclusion (prior phase)
-----------------------------------------
Results are consistent with a general RF/select-associated host wake-up,
not a command-specific trigger.
"""
    (output / "README.txt").write_text(readme, encoding="utf-8")
    commands = f"""# Prepared COM6 / {port} commands for {name}
python -m elatec_uid_tool capture-application-block --port {port} --label reference-baseline --state baseline-idle --notes "Idle baseline"
python -m elatec_uid_tool logic-analyzer --port {port} --duration 5 --session-only --verbose
python -m elatec_uid_tool capture-application-block --port {port} --label reference-after-session --state after-session-monitor
python -m elatec_uid_tool trigger-analysis --port {port} --all --verbose
python -m elatec_uid_tool capture-application-block --port {port} --label reference-after-trigger --state after-trigger-analysis
python -m elatec_uid_tool capture-application-block --port {port} --label reference-before-display --state before-display-update
python -m elatec_uid_tool capture-application-block --port {port} --label reference-after-display --state after-display-update
python -m elatec_uid_tool build-application-dataset captures/application-block --output captures/application-datasets/{name} --representative-only
python -m elatec_uid_tool compare-application-dataset captures/application-datasets/{name} --mode inter-tag
python -m elatec_uid_tool compare-application-captures captures/application-block/<before> captures/application-block/<after> --mode intra-tag
"""
    (output / "capture_commands.txt").write_text(commands, encoding="utf-8")
    return output
