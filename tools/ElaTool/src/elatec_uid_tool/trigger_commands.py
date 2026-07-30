from __future__ import annotations

from pathlib import Path

from .analysis.trigger import SCENARIO_IDS, TriggerAnalysis, TriggerConfig
from .ports import resolve_port
from .protocol import ElatecError


def command_trigger_analysis(args) -> int:
    if getattr(args, "all", False):
        scenarios = list(SCENARIO_IDS)
    elif getattr(args, "scenario", None):
        scenarios = [args.scenario]
    else:
        scenarios = list(SCENARIO_IDS)

    port = resolve_port(args.port, args.timeout)
    config = TriggerConfig(
        port=port,
        scenarios=scenarios,
        duration_s=args.duration,
        interval_ms=args.interval_ms,
        settle_ms=args.settle_ms,
        repetitions=args.repetitions,
        output_dir=Path(args.output_dir),
        verbose=bool(args.verbose),
        timeout=args.timeout,
        wait_tag_s=args.wait,
    )

    print("Trigger Analysis")
    print("================")
    print(f"Port:         {port}")
    print(f"Scenarios:    {', '.join(scenarios)}")
    print(f"Duration:     {config.duration_s:g} s")
    print(f"Interval:     {config.interval_ms:g} ms")
    print(f"Settle:       {config.settle_ms:g} ms")
    print(f"Repetitions:  {config.repetitions}")
    print(f"Output:       {config.output_dir}")
    print("Mode:         READ-ONLY (no SRAM)")
    print()

    try:
        result = TriggerAnalysis(config).run()
    except (ElatecError, ValueError, OSError, RuntimeError) as exc:
        print(f"\nCHYBA: {exc}")
        return 2

    print()
    print("Souhrn")
    print("------")
    print(f"UID:         {result.uid}")
    print(f"Capture dir: {result.directory}")
    for scenario, aggregate in result.metadata.get("aggregates", {}).items():
        print(f"  {scenario}: {aggregate.get('conclusion')}")
    print()
    print("Hotovo. Nebyl proveden žádný zápis do tagu.")
    return 0
