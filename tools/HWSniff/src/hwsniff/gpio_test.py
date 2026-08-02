"""Interactive / automated GPIO hardware self-test CLI."""

from __future__ import annotations

import time
from typing import Any, Callable

from .buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from .configuration import DEFAULT_CONFIG, deep_merge
from .dip import DipReader
from .gpio_backend import GpioBackend, MockGpioBackend, create_backend
from .leds import LED_NAMES, LedController, LedPins
from .network import NetworkMonitor
from .patterns import PatternKind


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

    backend = gpio or create_backend(prefer_mock=bool(cfg.get("gpio_prefer_mock")))
    print("HWSniff GPIO TEST")
    print(f"Backend: {type(backend).__name__}")

    dip = DipReader(
        backend,
        dip1_pin=int(dip_cfg.get("dip1", 22)),
        dip2_pin=int(dip_cfg.get("dip2", 18)),
        active_low=bool(dip_cfg.get("active_low", True)),
        pull_up=bool(dip_cfg.get("pull_up", True)),
    )
    info = dip.describe()
    print(f"DIP1: {info['dip1']}")
    print(f"DIP2: {info['dip2']}")
    print(f"MODE: {info['mode'].replace('MODE_', '')}")

    leds = LedController(
        backend,
        LedPins(
            green=int(led_cfg.get("green", 5)),
            yellow=int(led_cfg.get("yellow", 6)),
            red=int(led_cfg.get("red", 12)),
            blue=int(led_cfg.get("blue", 13)),
            orange=int(led_cfg.get("orange", 19)),
            active_high=bool(led_cfg.get("active_high", True)),
        ),
    )
    for name in LED_NAMES:
        leds.all_off()
        leds.set_pattern(name, PatternKind.ON)
        end = clock() + 0.2
        while clock() < end:
            leds.tick()
            sleep(0.01)
        label = f"{name.upper()} LED"
        print(f"{label:14s} OK")
    leds.all_off()
    leds.tick()

    net = NetworkMonitor(
        interface=str(net_cfg.get("interface", "wlan0")),
        poll_seconds=0,
        clock=clock,
    )
    net._next = 0  # force immediate
    net.tick()
    print(f"WLAN: {net.status.value.replace('WLAN_', '')}")
    if net.ip:
        print(f"IP: {net.ip}")

    if wait_buttons:
        buttons = ButtonWatcher(
            backend,
            ButtonConfig(
                start_pin=int(btn_cfg.get("start", 17)),
                stop_pin=int(btn_cfg.get("stop", 27)),
                active_low=bool(btn_cfg.get("active_low", True)),
                pull_up=bool(btn_cfg.get("pull_up", True)),
                debounce_ms=int(btn_cfg.get("debounce_ms", 50)),
            ),
            clock=clock,
        )
        for expect, label in (
            (ButtonEvent.START_SHORT, "START"),
            (ButtonEvent.STOP_SHORT, "STOP"),
        ):
            print(f"Press {label}...")
            if isinstance(backend, MockGpioBackend) and input_fn is None:
                # Auto-simulate for mock/CI
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
