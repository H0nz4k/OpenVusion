from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .capture import CaptureProbe, ProbeConfig
from .detection import ReaderSelectionError, resolve_reader_port
from .status import OverallStatus


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="twn4_capture_probe",
        description=(
            "Windows read-only ELATEC TWN4 diagnostic: wait for one tag, "
            "run one capture, save results immediately, exit."
        ),
    )
    p.add_argument("--port", help="COM port, např. COM5")
    p.add_argument(
        "--auto-port",
        action="store_true",
        help="Automaticky najít jednu ELATEC TWN4 čtečku",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("capture") / "windows_probe",
        help="Kořenový výstupní adresář (default: capture/windows_probe)",
    )
    p.add_argument(
        "--raw-trace",
        action="store_true",
        help="Ukládat TX/RX Simple Protocol hex do raw_serial.jsonl",
    )
    p.add_argument("--tag-timeout", type=float, default=60.0)
    p.add_argument("--retry-count", type=int, default=3)
    p.add_argument("--retry-delay-ms", type=float, default=150.0)
    p.add_argument("--session-seconds", type=float, default=2.0)
    p.add_argument("--skip-eeprom", action="store_true")
    p.add_argument("--skip-application", action="store_true")
    p.add_argument("--skip-session", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selected = resolve_reader_port(port=args.port, auto_port=args.auto_port)
    except ReaderSelectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.verbose:
        print(
            f"Reader: {selected.device} "
            f"({selected.description or selected.product or 'ELATEC'})",
            flush=True,
        )

    config = ProbeConfig(
        port=selected.device,
        output=args.output,
        raw_trace=args.raw_trace,
        tag_timeout=args.tag_timeout,
        retry_count=args.retry_count,
        retry_delay_ms=args.retry_delay_ms,
        session_seconds=args.session_seconds,
        skip_eeprom=args.skip_eeprom,
        skip_application=args.skip_application,
        skip_session=args.skip_session,
        verbose=args.verbose,
    )
    result = CaptureProbe(config).run()
    if result.overall == OverallStatus.SUCCESS:
        return 0
    if result.overall == OverallStatus.PARTIAL:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
