from __future__ import annotations

import json
from pathlib import Path

from .analysis.application_block import (
    analyze_application_block,
    analyze_application_block_file,
    compare_application_block_files,
    read_application_block_from_tag,
)
from .analysis.application_capture import ApplicationBlockCapture, CaptureConfig
from .analysis.application_dataset import (
    DatasetBuildConfig,
    build_application_dataset,
    write_study_plan,
)
from .analysis.application_study import (
    compare_captures,
    compare_dataset,
    comparison_to_text,
)
from .ports import resolve_port
from .protocol import ElatecError, SimpleProtocolClient


def command_application_block(args) -> int:
    port = resolve_port(args.port, args.timeout)
    print(f"Otevírám {port} (read-only application block 0x30–0x37)...")
    try:
        with SimpleProtocolClient(port, timeout=args.timeout) as client:
            block, uid, version = read_application_block_from_tag(client)
    except (ElatecError, RuntimeError, ValueError) as exc:
        print(f"CHYBA: {exc}")
        return 2

    report = analyze_application_block(
        block,
        source=f"tag:{port}",
        uid=uid,
    )
    print(report.to_text())
    if getattr(args, "output", None):
        path = Path(args.output)
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Uloženo: {path}")
    print(f"GET_VERSION: {version.hex(' ').upper()}")
    return 0


def command_analyze_application_block(args) -> int:
    path = Path(args.dump)
    try:
        report = analyze_application_block_file(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(report.to_text())
    if getattr(args, "output", None):
        out = Path(args.output)
        out.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Uloženo: {out}")
    return 0


def command_compare_application_blocks(args) -> int:
    paths = [Path(item) for item in args.dumps]
    try:
        comparison = compare_application_block_files(paths)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(comparison.to_text())
    if getattr(args, "output", None):
        out = Path(args.output)
        out.write_text(
            json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Uloženo: {out}")
    return 0 if not comparison.variable_offsets else 1


def command_capture_application_block(args) -> int:
    port = resolve_port(args.port, args.timeout)
    config = CaptureConfig(
        port=port,
        label=args.label,
        state=args.state,
        notes=args.notes or "",
        samples=args.samples,
        interval_ms=args.interval_ms,
        output_dir=Path(args.output_dir),
        include_full_dump=bool(args.include_full_dump),
        verbose=bool(args.verbose),
        timeout=args.timeout,
        wait_tag_s=getattr(args, "wait", 15.0),
    )
    print("Application Block Capture (READ-ONLY)")
    print(f"Port:    {port}")
    print(f"Label:   {config.label}")
    print(f"State:   {config.state}")
    print(f"Samples: {config.samples}")
    print()
    try:
        result = ApplicationBlockCapture(config).run()
    except (ElatecError, RuntimeError, ValueError, OSError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    meta = result.metadata
    print(f"UID:     {meta.get('uid')}")
    print(f"Stable:  {meta.get('stable_across_samples')}")
    print(f"Output:  {result.directory}")
    return 0 if meta.get("successful_samples", 0) else 2


def command_build_application_dataset(args) -> int:
    config = DatasetBuildConfig(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output),
        representative_only=bool(args.representative_only),
        uid_filter=args.uid,
        state_filter=args.state,
        label_filter=args.label,
    )
    try:
        result = build_application_dataset(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(f"Dataset: {result.directory}")
    print(f"Records: {result.manifest['counts']['records']}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


def command_compare_application_captures(args) -> int:
    paths = [Path(item) for item in args.captures]
    try:
        report = compare_captures(paths, mode=args.mode)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(comparison_to_text(report))
    if getattr(args, "output", None):
        out = Path(args.output)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Uloženo: {out}")
    return 0


def command_compare_application_dataset(args) -> int:
    try:
        report = compare_dataset(Path(args.dataset), mode=args.mode)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(comparison_to_text(report))
    if getattr(args, "output", None):
        out = Path(args.output)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Uloženo: {out}")
    return 0


def command_application_study_plan(args) -> int:
    try:
        path = write_study_plan(
            name=args.name,
            output_dir=Path(args.output),
            port=getattr(args, "port", "COM6"),
        )
    except OSError as exc:
        print(f"CHYBA: {exc}")
        return 2
    print(f"Study plan: {path}")
    print(f"  README.txt")
    print(f"  capture_commands.txt")
    print(f"  study.json")
    return 0
