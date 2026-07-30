from __future__ import annotations

from pathlib import Path

from .capture.logic_analyzer import LogicAnalyzerCapture, LogicAnalyzerConfig
from .ports import resolve_port
from .protocol import ElatecError


def command_logic_analyzer(args) -> int:
    port = resolve_port(args.port, args.timeout)
    output_dir = Path(args.output_dir)

    config = LogicAnalyzerConfig(
        port=port,
        duration_s=args.duration,
        interval_ms=args.interval_ms,
        output_dir=output_dir,
        watch_eeprom=bool(args.watch_eeprom),
        verbose=bool(args.verbose),
        timeout=args.timeout,
        wait_tag_s=args.wait,
    )

    print("NFC Logic Analyzer")
    print("==================")
    print(f"Port:          {port}")
    print(f"Duration:      {config.duration_s:g} s")
    print(f"Interval:      {config.interval_ms:g} ms")
    print(f"Watch EEPROM:  {config.watch_eeprom}")
    print(f"Output:        {output_dir}")
    print("Mode:          READ-ONLY")
    print("Timeline:      session -> SRAM"
          + (" -> EEPROM 0x30-0x37" if config.watch_eeprom else ""))
    print()

    capture = LogicAnalyzerCapture(config)
    try:
        result = capture.run()
    except (ElatecError, ValueError, OSError) as exc:
        print(f"\nCHYBA: {exc}")
        if capture._writer is not None:
            print(f"Částečný capture: {capture._writer.directory}")
        return 2
    except KeyboardInterrupt:
        print("\nPřerušeno uživatelem. Ukládám částečný capture...")
        if capture._writer is not None:
            print(f"Capture: {capture._writer.directory}")
        return 130

    print()
    print("Souhrn")
    print("------")
    print(f"UID:              {result.uid}")
    print(f"Sample cycles:    {result.sample_cycles}")
    print(f"Events:           {result.event_count}")
    print(f"Errors:           {result.error_count}")
    print(f"Partial:          {result.partial}")
    print(f"Capture dir:      {result.directory}")
    print()
    print("Hotovo. Nebyl proveden žádný zápis do tagu.")
    return 0
