"""HWSniff v2 diagnostic dump (no tag capture)."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .configuration import GPIO_PHYSICAL, deep_merge, DEFAULT_CONFIG
from .dip import DipReader
from .gpio_backend import create_backend
from .network import NetworkMonitor
from .reader_monitor import ReaderMonitor


def _pi_model() -> str:
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        try:
            return model_path.read_text("utf-8", errors="replace").strip("\x00").strip()
        except OSError:
            pass
    return platform.platform()


def _gpio_backend_name(prefer_mock: bool) -> str:
    if prefer_mock:
        return "MockGpioBackend"
    try:
        import gpiozero  # noqa: F401

        return "GpioZeroBackend"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def _perm_ok(path: Path) -> str:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".hwsniff_diag_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return "writable"
    except OSError as exc:
        return f"not_writable: {exc}"


def run_diagnostics(config: dict[str, Any] | None = None) -> int:
    cfg = deep_merge(DEFAULT_CONFIG, config or {})
    gpio_cfg = cfg.get("gpio") or {}
    btn = gpio_cfg.get("buttons") or {}
    dip_cfg = gpio_cfg.get("dip") or {}
    leds = gpio_cfg.get("leds") or {}
    net_cfg = cfg.get("network") or {}

    from .runtime import ensure_runtime_cwd

    runtime = ensure_runtime_cwd(cfg)

    print("HWSniff diagnostics")
    print(f"  version:          {__version__}")
    print(f"  hardware_profile: {cfg.get('hardware_profile')}")
    print(f"  Pi model:         {_pi_model()}")
    print(f"  runtime cwd:      {runtime}")
    print(f"  GPIO backend:     {_gpio_backend_name(bool(cfg.get('gpio_prefer_mock')))}")

    # Permissions
    for label, path in (
        ("gpiochip", Path("/dev/gpiochip0")),
        ("ttyACM", Path("/dev/ttyACM0")),
    ):
        exists = path.exists()
        print(f"  {label}:           {'present' if exists else 'absent'} ({path})")

    data_root = Path(cfg.get("data_root", "/var/lib/hwsniff"))
    log_root = Path(cfg.get("log_root", "/var/log/hwsniff"))
    capture_root = Path(cfg.get("capture_root", str(data_root / "captures")))
    print(f"  storage:          {_perm_ok(data_root)} ({data_root})")
    print(f"  capture dir:      {_perm_ok(capture_root)} ({capture_root})")
    print(f"  log dir:          {_perm_ok(log_root)} ({log_root})")
    try:
        free = shutil.disk_usage(data_root if data_root.exists() else Path.cwd()).free
        print(f"  free space:       {free // (1024 * 1024)} MiB")
    except OSError as exc:
        print(f"  free space:       error: {exc}")

    prefer_mock = bool(cfg.get("gpio_prefer_mock"))
    backend = create_backend(prefer_mock=prefer_mock, runtime_config=cfg)
    try:
        dip = DipReader(
            backend,
            dip1_pin=int(dip_cfg.get("dip1", 12)),
            dip2_pin=int(dip_cfg.get("dip2", 13)),
            active_low=bool(dip_cfg.get("active_low", True)),
            pull_up=bool(dip_cfg.get("pull_up", True)),
        )
        info = dip.describe()
        print(f"  DIP1:             {info['dip1']} (BCM {dip_cfg.get('dip1', 12)} / pin {GPIO_PHYSICAL['dip1']})")
        print(f"  DIP2:             {info['dip2']} (BCM {dip_cfg.get('dip2', 13)} / pin {GPIO_PHYSICAL['dip2']})")
        print(f"  DIP mode:         {info['mode']}")

        print("  GPIO map:")
        print(f"    START  BCM {btn.get('start', 5):2}  physical {GPIO_PHYSICAL['start']}")
        print(f"    STOP   BCM {btn.get('stop', 6):2}  physical {GPIO_PHYSICAL['stop']}")
        print(f"    GREEN  BCM {leds.get('green', 19):2}  physical {GPIO_PHYSICAL['green']}")
        print(f"    YELLOW BCM {leds.get('yellow', 16):2}  physical {GPIO_PHYSICAL['yellow']}")
        print(f"    RED    BCM {leds.get('red', 26):2}  physical {GPIO_PHYSICAL['red']}")
        print(f"    BLUE   BCM {leds.get('blue', 20):2}  physical {GPIO_PHYSICAL['blue']}")

        net = NetworkMonitor(
            interface=str(net_cfg.get("interface", "wlan0")),
            poll_seconds=0,
        )
        net._next = 0
        net.tick()
        print(f"  WLAN:             {net.status.value.replace('WLAN_', '')}")
        print(f"  IP:               {net.ip or '-'}")

        mon = ReaderMonitor(cfg)
        presence = mon.probe()
        print(f"  TWN4 present:     {presence.present}")
        print(f"  TWN4 port:        {presence.port or '-'}")
        print(f"  TWN4 version:     {presence.version or presence.error or '-'}")
    finally:
        backend.close()

    print("diagnostics complete (no capture performed)")
    return 0
