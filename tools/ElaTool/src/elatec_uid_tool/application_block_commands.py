from __future__ import annotations

import json
from pathlib import Path

from .analysis.application_block import (
    analyze_application_block,
    analyze_application_block_file,
    compare_application_block_files,
    read_application_block_from_tag,
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
