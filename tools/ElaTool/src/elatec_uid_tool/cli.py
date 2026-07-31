from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import (
    command_analyze,
    command_analyze_application_block,
    command_application_block,
    command_application_study_plan,
    command_build_application_dataset,
    command_capture,
    command_capture_application_block,
    command_compare_application_blocks,
    command_compare_application_captures,
    command_compare_application_dataset,
    command_interactive,
    command_logic_analyzer,
    command_prepare_reader,
    command_reader_info,
    command_test_medium,
    command_trigger_analysis,
    command_update_reader,
)
from .analysis.trigger import SCENARIO_IDS
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

    p = sub.add_parser(
        "trigger-analysis",
        help="Read-only RF trigger association analysis for session registers",
    )
    p.add_argument("--port", default="auto")
    p.add_argument("--scenario", choices=SCENARIO_IDS)
    p.add_argument("--all", action="store_true", help="Spustit všechny scénáře")
    p.add_argument("--duration", type=float, default=2.0)
    p.add_argument("--interval-ms", type=float, default=50.0)
    p.add_argument("--settle-ms", type=float, default=1500.0)
    p.add_argument(
        "--guard-ms",
        type=float,
        default=200.0,
        help="Krátká prodleva po completed_active_cycle před scénářem",
    )
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--output-dir", default="captures/trigger-analysis")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--wait", type=float, default=15.0)
    p.set_defaults(func=command_trigger_analysis)

    p = sub.add_parser(
        "application-block",
        help="Read-only read+analyze EEPROM application block 0x30–0x37 from tag",
    )
    p.add_argument("--port", default="auto")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--output", default=None, help="Volitelný JSON výstup")
    p.set_defaults(func=command_application_block)

    p = sub.add_parser(
        "analyze-application-block",
        help="Analyze application block 0x30–0x37 from JSON/BIN dump",
    )
    p.add_argument("dump", help="Cesta k JSON nebo BIN dumpu")
    p.add_argument("--output", default=None)
    p.set_defaults(func=command_analyze_application_block)

    p = sub.add_parser(
        "compare-application-blocks",
        help="Compare application blocks from two or more dumps",
    )
    p.add_argument("dumps", nargs="+", help="Dva nebo více JSON/BIN dumpů")
    p.add_argument("--output", default=None)
    p.set_defaults(func=command_compare_application_blocks)

    p = sub.add_parser(
        "capture-application-block",
        help="Repeated read-only capture of EEPROM application block 0x30–0x37",
    )
    p.add_argument("--port", default="auto")
    p.add_argument("--label", required=True, help="Experiment label")
    p.add_argument("--state", default="unspecified", help="Experimental state id")
    p.add_argument("--notes", default="")
    p.add_argument("--output-dir", default="captures/application-block")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--interval-ms", type=float, default=250.0)
    p.add_argument("--include-full-dump", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--wait", type=float, default=15.0)
    p.set_defaults(func=command_capture_application_block)

    p = sub.add_parser(
        "build-application-dataset",
        help="Build manifest/dataset from application-block capture directories",
    )
    p.add_argument("input_dir", help="Capture root or single capture directory")
    p.add_argument(
        "--output",
        required=True,
        help="Output dataset directory",
    )
    p.add_argument(
        "--representative-only",
        action="store_true",
        help="Include one representative block per capture",
    )
    p.add_argument("--uid", default=None)
    p.add_argument("--state", default=None)
    p.add_argument("--label", default=None)
    p.set_defaults(func=command_build_application_dataset)

    p = sub.add_parser(
        "compare-application-captures",
        help="Compare capture directories (intra-tag or inter-tag)",
    )
    p.add_argument("captures", nargs="+", help="Two or more capture directories")
    p.add_argument(
        "--mode",
        choices=("intra-tag", "inter-tag"),
        default="intra-tag",
    )
    p.add_argument("--output", default=None)
    p.set_defaults(func=command_compare_application_captures)

    p = sub.add_parser(
        "compare-application-dataset",
        help="Compare samples from an application-block dataset",
    )
    p.add_argument("dataset", help="Dataset directory with manifest.json")
    p.add_argument(
        "--mode",
        choices=("intra-tag", "inter-tag"),
        default="inter-tag",
    )
    p.add_argument("--output", default=None)
    p.set_defaults(func=command_compare_application_dataset)

    p = sub.add_parser(
        "application-study-plan",
        help="Write a manual read-only study plan (no RF writes)",
    )
    p.add_argument("--name", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--port", default="COM6")
    p.set_defaults(func=command_application_study_plan)
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
