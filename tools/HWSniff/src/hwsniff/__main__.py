from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from .configuration import (
    DEFAULT_CONFIG,
    ConfigError,
    deep_merge,
    load_config,
    write_example_config,
)
from .gpio_test import run_gpio_test


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hwsniff",
        description="OpenVusion HWSniff v2 — Pi Zero 2 W headless GPIO appliance "
        "(shared ElaTool/PCSniff capture engine).",
    )
    parser.add_argument(
        "--config",
        default="/etc/hwsniff/config.json",
        help="Path to config.json",
    )
    parser.add_argument(
        "--gpio-test",
        action="store_true",
        help="Run LED/DIP/button/WLAN/reader hardware self-test and exit",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print HWSniff/Pi/GPIO/reader/storage diagnostics (no capture)",
    )
    parser.add_argument(
        "--mock-gpio",
        action="store_true",
        help="Force MockGpioBackend (PC / CI)",
    )
    parser.add_argument(
        "--legacy-ui",
        action="store_true",
        help="Run legacy Waveshare/X11/pygame touchscreen UI",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Legacy UI flag (no pygame window). Ignored for GPIO app.",
    )
    parser.add_argument(
        "--write-example-config",
        metavar="PATH",
        help="Write example v2 config and exit",
    )
    args = parser.parse_args(argv)

    if args.write_example_config:
        write_example_config(Path(args.write_example_config))
        print(f"Wrote {args.write_example_config}")
        return 0

    config_path = Path(args.config)
    try:
        if config_path.exists():
            config = load_config(config_path)
        else:
            config = deep_merge(DEFAULT_CONFIG, {})
            config["data_root"] = str(Path.cwd() / "data")
            config["capture_root"] = str(Path.cwd() / "data" / "captures")
            config["log_root"] = str(Path.cwd() / "logs")
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", flush=True)
        return 2

    if args.mock_gpio:
        config["gpio_prefer_mock"] = True

    # lgpio/gpiozero create notify pipes in cwd — never use /opt/Sniff for that.
    from .runtime import ensure_runtime_cwd

    ensure_runtime_cwd(config)

    if args.gpio_test:
        logging.basicConfig(level=logging.INFO)
        return run_gpio_test(config)

    if args.diagnostics:
        from .diagnostics import run_diagnostics

        return run_diagnostics(config)

    if args.legacy_ui:
        from .legacy.app import HWSniffApp as LegacyApp

        app = LegacyApp(
            config=config if not config_path.exists() else config_path,
            headless=args.headless,
        )
        return app.run()

    from .app import HeadlessApp

    def shutdown_cb() -> None:
        cmd = (config.get("shutdown") or {}).get("command") or [
            "systemctl",
            "poweroff",
        ]
        logging.getLogger("hwsniff").warning("Executing shutdown: %s", cmd)
        try:
            subprocess.run(cmd, check=False)
        except OSError as exc:
            logging.getLogger("hwsniff").error("shutdown failed: %s", exc)

    app = HeadlessApp(config=config, shutdown_callback=shutdown_cb)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
