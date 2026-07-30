from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import (
    command_analyze,
    command_capture,
    command_interactive,
    command_logic_analyzer,
    command_prepare_reader,
    command_reader_info,
    command_test_medium,
    command_update_reader,
)
from . import ports as _ports
from .ports import (
    print_ports,
    probable_elatec_ports,
    recommended_port_index,
    resolve_port_selection,
)
from .protocol import enumerate_ports
from .presentation import print_matches
from .protocol import ElatecError


def select_port_interactively(timeout: float = 1.2) -> str:
    original = _ports.enumerate_ports
    _ports.enumerate_ports = enumerate_ports
    try:
        return _ports.select_port_interactively(timeout)
    finally:
        _ports.enumerate_ports = original


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elatec-uid", description="ELATEC TWN4 UID analyzer")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ports")
    p.set_defaults(func=lambda args: (print_ports() is not None) and 0)

    p = sub.add_parser("reader-info")
    p.add_argument("--port", default="auto")
    p.add_argument("--timeout", type=float, default=1.2)
    p.set_defaults(func=command_reader_info)

    p = sub.add_parser("test-medium")
    p.add_argument("--port", default="auto")
    p.add_argument("--timeout", type=float, default=1.2)
    p.add_argument("--wait", type=float, default=30.0)
    p.add_argument("--poll-interval", type=float, default=0.12)
    p.add_argument("--max-id-bytes", type=int, default=32)
    p.set_defaults(func=command_test_medium)

    p = sub.add_parser("capture")
    p.add_argument("--port", default="auto")
    p.add_argument("--expected", required=True)
    p.add_argument("--expected-format", choices=("auto", "decimal", "hexadecimal"), default="auto")
    p.add_argument("--timeout", type=float, default=1.2)
    p.add_argument("--wait", type=float, default=30.0)
    p.add_argument("--poll-interval", type=float, default=0.12)
    p.add_argument("--max-id-bytes", type=int, default=32)
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--show-all-candidates", action="store_true")
    p.add_argument("--output", default="results/last-capture.json")
    p.add_argument("--sample-store", default="data/samples.json")
    p.set_defaults(func=command_capture)

    p = sub.add_parser("analyze")
    p.add_argument("--raw", required=True)
    p.add_argument("--bits", type=int)
    p.add_argument("--expected", required=True)
    p.add_argument("--expected-format", choices=("auto", "decimal", "hexadecimal"), default="auto")
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--show-all-candidates", action="store_true")
    p.set_defaults(func=command_analyze)

    p = sub.add_parser("interactive")
    p.add_argument("--timeout", type=float, default=1.2)
    p.add_argument("--wait", type=float, default=30.0)
    p.add_argument("--poll-interval", type=float, default=0.12)
    p.add_argument("--max-id-bytes", type=int, default=32)
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--show-all-candidates", action="store_true")
    p.add_argument("--sample-store", default="data/samples.json")
    p.set_defaults(func=command_interactive)

    p = sub.add_parser("prepare-reader")
    p.add_argument("--devpack", required=True)
    p.set_defaults(func=command_prepare_reader)

    p = sub.add_parser("update-reader")
    p.add_argument("--devpack", default="files520")
    p.set_defaults(func=command_update_reader)

    p = sub.add_parser(
        "logic-analyzer",
        help="Read-only NFC Logic Analyzer (default: session-only timeline)",
    )
    p.add_argument("--port", default="auto")
    p.add_argument("--duration", type=float, default=5.0, help="Délka capture v sekundách")
    p.add_argument(
        "--interval-ms",
        type=float,
        default=50.0,
        help="Cílový interval vzorkování v milisekundách",
    )
    p.add_argument(
        "--output-dir",
        default="captures/logic-analyzer",
        help="Kořenový adresář pro výstupy capture",
    )
    p.add_argument(
        "--session-only",
        action="store_true",
        help="Pouze session registry (výchozí bezpečný režim)",
    )
    p.add_argument(
        "--enable-experimental-sram",
        action="store_true",
        help=(
            "EXPERIMENTÁLNÍ: pokusit se o FAST_READ SRAM 0xF0–0xFF "
            "(fyzicky neověřeno; při NAK se sampler vypne)"
        ),
    )
    p.add_argument(
        "--watch-eeprom",
        action="store_true",
        help="Volitelně sledovat EEPROM stránky 0x30–0x37",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--wait", type=float, default=15.0, help="Čekání na tag v sekundách")
    p.set_defaults(func=command_logic_analyzer)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\nUkončeno uživatelem.", file=sys.stderr)
        return 130
    except (ElatecError, ValueError) as exc:
        print(f"\nCHYBA: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
