import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

TARGET_VID = 0x2FE3
TARGET_PID = 0x0001


def discover_one():
    matches = [
        p for p in list_ports.comports()
        if p.vid == TARGET_VID and p.pid == TARGET_PID
    ]
    if len(matches) != 1:
        return None
    return matches[0].device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--out")
    args = ap.parse_args()

    port = args.port or discover_one()
    if not port:
        raise SystemExit(
            "Nelze jednoznačně najít OpenVusion v0.6.1 (VID:PID 2fe3:0001)."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out or f"openvusion_rf_v061_{stamp}.csv")

    with serial.Serial(
        port,
        115200,
        timeout=1,
        write_timeout=2,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    ) as s, out.open("w", newline="", encoding="utf-8") as f:

        s.dtr = True
        time.sleep(1.0)
        s.reset_input_buffer()

        writer = csv.writer(f)
        writer.writerow(
            ["host_time", "sweep", "device_ms", "freq_mhz", "rssi_dbm"]
        )

        s.write(b"SCAN START\r\n")
        s.flush()

        print("Port:", port)
        print("Capture:", out)
        print("Ctrl+C = stop")

        try:
            while True:
                raw = s.readline().decode(
                    "utf-8", errors="replace"
                ).strip()

                if not raw.startswith("SWEEP,"):
                    if raw:
                        print(raw)
                    continue

                parts = raw.split(",")
                if len(parts) < 4:
                    continue

                host_time = datetime.now().isoformat(
                    timespec="milliseconds"
                )

                for item in parts[3:]:
                    if ":" not in item:
                        continue
                    freq, rssi = item.split(":", 1)
                    if rssi.startswith("ERR"):
                        continue
                    writer.writerow(
                        [host_time, parts[1], parts[2], freq, rssi]
                    )

                f.flush()

        except KeyboardInterrupt:
            try:
                s.write(b"SCAN STOP\r\n")
                s.flush()
            except Exception:
                pass
            print("\nSTOP")


if __name__ == "__main__":
    main()
