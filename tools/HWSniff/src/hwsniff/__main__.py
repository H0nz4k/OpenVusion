from __future__ import annotations

import argparse
from pathlib import Path

from .app import HWSniffApp
from .configuration import DEFAULT_CONFIG, write_example_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hwsniff")
    parser.add_argument(
        "--config",
        default="/etc/hwsniff/config.json",
        help="Path to config.json",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--write-example-config",
        metavar="PATH",
        help="Write example config and exit",
    )
    args = parser.parse_args(argv)
    if args.write_example_config:
        write_example_config(Path(args.write_example_config))
        print(f"Wrote {args.write_example_config}")
        return 0
    config_path = Path(args.config)
    if config_path.exists():
        app = HWSniffApp(config_path, headless=args.headless)
    else:
        cfg = dict(DEFAULT_CONFIG)
        cfg["data_root"] = str(Path.cwd() / "data")
        cfg["capture_root"] = str(Path.cwd() / "data" / "captures")
        cfg["log_root"] = str(Path.cwd() / "logs")
        app = HWSniffApp(config=cfg, headless=args.headless)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
