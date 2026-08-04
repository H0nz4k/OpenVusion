"""Interactive / automated GPIO hardware self-test CLI (HWSniff v2)."""

from __future__ import annotations

import time
from typing import Any, Callable

from .buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from .configuration import DEFAULT_CONFIG, GPIO_PHYSICAL, deep_merge
from .dip import DipReader
from .gpio_backend import GpioBackend, MockGpioBackend, create_backend
from .leds import LED_NAMES, LedController, LedPins
from .network import NetworkMonitor
from .patterns import PatternKind
from .reader_monitor import ReaderMonitor
from . import __version__


def run_gpio_test(
    config: dict[str, Any] | None = None,
    *,
    gpio: GpioBackend | None = None,
    wait_buttons: bool = True,
    button_timeout_s: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    input_fn: Callable[[str], None] | None = None,
) -> int:
    cfg = deep_merge(DEFAULT_CONFIG, config or {})
    gpio_cfg = cfg.get("gpio") or {}
    btn_cfg = gpio_cfg.get("buttons") or {}
    dip_cfg = gpio_cfg.get("dip") or {}
    led_cfg = gpio_cfg.get("leds") or {}
    net_cfg = cfg.get("network") or {}
    self_test = cfg.get("self_test") or {}

    from .runtime import ensure_runtime_cwd

    ensure_runtime_cwd(cfg)
    backend = gpio or create_backend(
        prefer_mock=bool(cfg.get("gpio_prefer_mock")),
        runtime_config=cfg,
    )
    print("HWSniff v2 GPIO TEST")
    print(f"Version: {__version__}")
    print(f"Backend: {type(backend).__name__}")
    print("Pin map (BCM -> physical):")
    mapping = [
        ("START", int(btn_cfg.get("start", 21)), GPIO_PHYSICAL["start"]),
        ("STOP", int(btn_cfg.get("stop", 6)), GPIO_PHYSICAL["stop"]),
        ("DIP1", int(dip_cfg.get("dip1", 12)), GPIO_PHYSICAL["dip1"]),
        ("DIP2", int(dip_cfg.get("dip2", 13)), GPIO_PHYSICAL["dip2"]),
        ("GREEN", int(led_cfg.get("green", 19)), GPIO_PHYSICAL["green"]),
        ("YELLOW", int(led_cfg.get("yellow", 16)), GPIO_PHYSICAL["yellow"]),
        ("RED", int(led_cfg.get("red", 26)), GPIO_PHYSICAL["red"]),
        ("BLUE", int(led_cfg.get("blue", 20)), GPIO_PHYSICAL["blue"]),
    ]
    for name, bcm, phys in mapping:
        print(f"  {name:7s} BCM {bcm:2d}  physical pin {phys}")

    dip = DipReader(
        backend,
        dip1_pin=int(dip_cfg.get("dip1", 12)),
        dip2_pin=int(dip_cfg.get("dip2", 13)),
        active_low=bool(dip_cfg.get("active_low", True)),
        pull_up=bool(dip_cfg.get("pull_up", True)),
    )
    info = dip.describe()
    print(f"DIP1: {info['dip1']}")
    print(f"DIP2: {info['dip2']} ({info.get('dip2_note', '')})")
    print(f"MODE: {info['mode'].replace('MODE_', '')}")

    leds = LedController(
        backend,
        LedPins(
            green=int(led_cfg.get("green", 19)),
            yellow=int(led_cfg.get("yellow", 16)),
            red=int(led_cfg.get("red", 26)),
            blue=int(led_cfg.get("blue", 20)),
            active_high=bool(led_cfg.get("active_high", True)),
        ),
    )
    led_ms = int(self_test.get("led_ms", 500)) / 1000.0
    cycles = int(self_test.get("cycles", 2))
    for cycle in range(cycles):
        print(f"LED self-test cycle {cycle + 1}/{cycles}")
        for name in LED_NAMES:
            leds.all_off()
            leds.set_pattern(name, PatternKind.ON)
            leds.tick()
            sleep(led_ms)
            print(f"  {name.upper():7s} OK")
    leds.all_off()
    leds.tick()

    net = NetworkMonitor(
        interface=str(net_cfg.get("interface", "wlan0")),
        poll_seconds=0,
        clock=clock,
    )
    net._next = 0
    net.tick()
    print(f"WLAN: {net.status.value.replace('WLAN_', '')}")
    if net.ip:
        print(f"IP: {net.ip}")

    mon = ReaderMonitor(cfg)
    presence = mon.probe()
    print(f"READER: {'PRESENT' if presence.present else 'MISSING'}")
    if presence.port:
        print(f"READER PORT: {presence.port}")
    if presence.version:
        print(f"READER VERSION: {presence.version}")
    elif presence.error:
        print(f"READER NOTE: {presence.error}")

    if wait_buttons:
        buttons = ButtonWatcher(
            backend,
            ButtonConfig(
                start_pin=int(btn_cfg.get("start", 21)),
                stop_pin=int(btn_cfg.get("stop", 6)),
                active_low=bool(btn_cfg.get("active_low", True)),
                pull_up=bool(btn_cfg.get("pull_up", True)),
                debounce_ms=int(btn_cfg.get("debounce_ms", 50)),
            ),
            clock=clock,
        )
        _ = buttons.poll()

        for expect, label in (
            (ButtonEvent.START_SHORT, "START"),
            (ButtonEvent.STOP_SHORT, "STOP"),
        ):
            print(f"Press {label}...")
            if isinstance(backend, MockGpioBackend) and input_fn is None:
                pin = (
                    buttons.config.start_pin
                    if expect == ButtonEvent.START_SHORT
                    else buttons.config.stop_pin
                )
                backend.press_active_low(pin)
                deadline = clock() + 0.2
                while clock() < deadline:
                    buttons.poll()
                    sleep(0.01)
                backend.release_active_low(pin)
            deadline = clock() + button_timeout_s
            seen = False
            while clock() < deadline:
                for ev in buttons.poll():
                    if ev == expect:
                        print(f"{label} detected")
                        seen = True
                        break
                if seen:
                    break
                sleep(0.02)
            if not seen:
                print(f"{label} NOT detected — FAIL")
                backend.close()
                return 1

    backend.close()
    print("GPIO TEST PASSED")
    return 0
