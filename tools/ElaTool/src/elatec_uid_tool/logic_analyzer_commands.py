from __future__ import annotations

from pathlib import Path

from .capture.logic_analyzer import LogicAnalyzerCapture, LogicAnalyzerConfig
from .ports import resolve_port
from .protocol import ElatecError


EXPERIMENTAL_SRAM_WARNING = """
POZOR: experimentální SRAM režim
--------------------------------
FAST_READ 0xF0–0xFF NENÍ fyzicky ověřený způsob čtení SRAM na NTAG I²C Plus 1K.
Fyzický test (2026-07-31) vrátil Type-2 NAK: invalid address or command range
při NC_REG=0x19 (pass-through vypnutý).

Podle NXP datasheetu je RF mapa F0–FF platná jen v pass-through režimu.
Tento nástroj pass-through NEZAPÍNÁ (read-only).

Při NAK bude SRAM sampler deaktivován a provede se SearchTag recovery.
""".strip()


def command_logic_analyzer(args) -> int:
    if getattr(args, "session_only", False) and getattr(
        args, "enable_experimental_sram", False
    ):
        print(
            "CHYBA: nelze kombinovat --session-only a --enable-experimental-sram.",
            flush=True,
        )
        return 2

    port = resolve_port(args.port, args.timeout)
    output_dir = Path(args.output_dir)
    enable_sram = bool(getattr(args, "enable_experimental_sram", False))
    session_only = bool(getattr(args, "session_only", False)) or not enable_sram

    config = LogicAnalyzerConfig(
        port=port,
        duration_s=args.duration,
        interval_ms=args.interval_ms,
        output_dir=output_dir,
        watch_eeprom=bool(args.watch_eeprom),
        enable_experimental_sram=enable_sram,
        session_only=session_only and not enable_sram,
        verbose=bool(args.verbose),
        timeout=args.timeout,
        wait_tag_s=args.wait,
    )

    print("NFC Logic Analyzer")
    print("==================")
    print(f"Port:              {port}")
    print(f"Duration:          {config.duration_s:g} s")
    print(f"Interval:          {config.interval_ms:g} ms")
    print(f"Session only:      {not config.sram_requested}")
    print(f"Experimental SRAM: {config.sram_requested}")
    print(f"Watch EEPROM:      {config.watch_eeprom}")
    print(f"Output:            {output_dir}")
    print("Mode:              READ-ONLY")
    strategy = "session"
    if config.sram_requested:
        strategy += " -> experimental-sram"
    if config.watch_eeprom:
        strategy += " -> EEPROM 0x30-0x37"
    print(f"Timeline:          {strategy}")
    print()

    if config.sram_requested:
        print(EXPERIMENTAL_SRAM_WARNING)
        print()

    capture = LogicAnalyzerCapture(config)
    try:
        result = capture.run()
    except (ElatecError, ValueError, OSError) as exc:
        print(f"\nCHYBA: {exc}")
        if capture._writer is not None:
            print(f"Částečný capture: {capture._writer.directory}")
            print(f"Finish status:    {capture._finish_status}")
        return 2
    except KeyboardInterrupt:
        print("\nPřerušeno uživatelem. Ukládám částečný capture...")
        if capture._writer is not None:
            print(f"Capture:       {capture._writer.directory}")
            print(f"Finish status: {capture._finish_status}")
        return 130

    print()
    print("Souhrn")
    print("------")
    print(f"UID:              {result.uid}")
    print(f"Finish status:    {result.finish_status}")
    print(f"Sample cycles:    {result.sample_cycles}")
    print(f"Events:           {result.event_count}")
    print(f"Errors:           {result.error_count}")
    samplers = result.metadata.get("samplers", {})
    session = samplers.get("session", {})
    sram = samplers.get("sram", {})
    print(
        f"Session samples:  ok={session.get('success', 0)} "
        f"fail={session.get('failure', 0)}"
    )
    print(
        f"SRAM samples:     ok={sram.get('success', 0)} "
        f"fail={sram.get('failure', 0)}"
    )
    print(f"Capture dir:      {result.directory}")
    print()
    print("Hotovo. Nebyl proveden žádný zápis do tagu.")

    if result.finish_status == "completed_successfully":
        return 0
    if result.finish_status == "completed_with_errors":
        return 1
    return 2
