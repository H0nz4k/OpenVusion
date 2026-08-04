#!/usr/bin/env python3
"""HWSniff v2 — test tlačítek START / STOP + DIP1 / DIP2 + raw úrovně.

GPIO (interní pull-up, OFF=HIGH/1, ON=LOW/0):
  START  BCM 21 / physical pin 40
  STOP   BCM 6  / physical pin 31
  DIP1   BCM 12 / physical pin 32
  DIP2   BCM 13 / physical pin 33

Spuštění na Pi:
  cd /var/lib/hwsniff
  sudo systemctl stop hwsniff
  sudo -u hwsniff /opt/Sniff/.venv/bin/python /opt/Sniff/test_buttons.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hwsniff.buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from hwsniff.dip import DipReader, dip_mode_from_levels
from hwsniff.gpio_backend import GpioZeroBackend, MockGpioBackend
from hwsniff.runtime import ensure_runtime_cwd

START_BCM, START_PHYS = 21, 40
STOP_BCM, STOP_PHYS = 6, 31
DIP1_BCM, DIP1_PHYS = 12, 32
DIP2_BCM, DIP2_PHYS = 13, 33


def _lvl(high: bool) -> str:
    return "HIGH" if high else "LOW "


def _make_backend():
    """Real GPIO only — never silently fall back to mock."""
    try:
        backend = GpioZeroBackend()
    except Exception as exc:
        print("FATAL: nelze otevřít GpioZeroBackend:", exc, file=sys.stderr)
        print(
            "Zkontroluj: python3-gpiozero, python3-lgpio, skupiny gpio,",
            "cwd=/var/lib/hwsniff, hwsniff.service zastavený.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    return backend


def main() -> int:
    runtime = ensure_runtime_cwd({"data_root": "/var/lib/hwsniff"})
    backend = _make_backend()
    if isinstance(backend, MockGpioBackend):
        print("FATAL: MockGpioBackend — fyzické piny se nečtou.", file=sys.stderr)
        return 1

    # gpiozero factory info
    factory_name = "?"
    try:
        from gpiozero import Device

        factory_name = type(Device.pin_factory).__name__
    except Exception as exc:  # noqa: BLE001
        factory_name = f"unknown ({exc})"

    buttons = ButtonWatcher(
        backend,
        ButtonConfig(
            start_pin=START_BCM,
            stop_pin=STOP_BCM,
            active_low=True,
            pull_up=True,
            debounce_ms=50,
            shutdown_hold_seconds=3.0,
        ),
    )
    dip = DipReader(
        backend,
        dip1_pin=DIP1_BCM,
        dip2_pin=DIP2_BCM,
        active_low=True,
        pull_up=True,
    )
    _ = buttons.poll()

    print()
    print("================================")
    print(" HWSniff v2 — BUTTON + DIP TEST")
    print("================================")
    print(f"  backend : {type(backend).__name__}")
    print(f"  factory : {factory_name}")
    print(f"  cwd     : {runtime}")
    print(f"  START  BCM {START_BCM:2}  pin {START_PHYS}")
    print(f"  STOP   BCM {STOP_BCM:2}  pin {STOP_PHYS}")
    print(f"  DIP1   BCM {DIP1_BCM:2}  pin {DIP1_PHYS}")
    print(f"  DIP2   BCM {DIP2_BCM:2}  pin {DIP2_PHYS}")
    print("  pull-up: OFF=HIGH(1)  ON/stisk=LOW(0)")
    print()
    print("Nejdřív: sudo systemctl stop hwsniff")
    print("Stiskni START/STOP, přepínej DIP. Ctrl+C = konec.")
    print("Každá změna LEVEL = pin se čte. Žádná změna = HW/pin/conflict.")
    print()

    last: tuple | None = None
    ticks = 0

    try:
        while True:
            start_high = backend.read(START_BCM)
            stop_high = backend.read(STOP_BCM)
            d1_on, d2_on = dip.read_raw()
            d1_high = not d1_on
            d2_high = not d2_on
            mode = dip_mode_from_levels(dip1_on=d1_on, dip2_on=d2_on)

            snap = (start_high, stop_high, d1_on, d2_on, mode.value)
            if snap != last:
                print(
                    f"  LEVEL  START={_lvl(start_high)} STOP={_lvl(stop_high)}  "
                    f"DIP1={_lvl(d1_high)}({'ON' if d1_on else 'OFF'})  "
                    f"DIP2={_lvl(d2_high)}({'ON' if d2_on else 'OFF'})  "
                    f"MODE={mode.value.replace('MODE_', '')}"
                )
                last = snap

            for ev in buttons.poll():
                if ev == ButtonEvent.START_SHORT:
                    print("  EVENT  START short")
                elif ev == ButtonEvent.STOP_SHORT:
                    print("  EVENT  STOP  short")
                elif ev == ButtonEvent.STOP_LONG:
                    print("  EVENT  STOP  LONG (3 s)")

            ticks += 1
            # Heartbeat každých ~5 s — důkaz, že loop běží
            if ticks % 250 == 0:
                print(
                    f"  ... alive  START={_lvl(start_high)} STOP={_lvl(stop_high)} "
                    f"DIP1={'ON' if d1_on else 'OFF'} DIP2={'ON' if d2_on else 'OFF'}"
                )
            time.sleep(0.02)
    except KeyboardInterrupt:
        print()
        print("Konec.")
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
