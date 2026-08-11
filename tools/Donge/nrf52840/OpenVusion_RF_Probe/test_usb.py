import argparse
import time

import serial
from serial.tools import list_ports

TARGET_VID = 0x2FE3
TARGET_PID = 0x0001
FW_VERSION = "0.7.0"


def discover():
    return [p for p in list_ports.comports() if p.vid == TARGET_VID and p.pid == TARGET_PID]


def read_for(ser, seconds):
    deadline = time.monotonic() + seconds
    chunks = []
    while time.monotonic() < deadline:
        data = ser.read(4096)
        if data:
            chunks.append(data)
        else:
            time.sleep(0.02)
    return b"".join(chunks)


def send(ser, cmd, expected=None, seconds=0.8):
    print(f">>> {cmd}")
    try:
        sent = ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()
    except serial.SerialTimeoutException:
        print("CHYBA: WRITE TIMEOUT")
        return None
    print("TX bytes:", sent)
    data = read_for(ser, seconds)
    print("RX raw:", repr(data))
    if data:
        print(data.decode("utf-8", errors="replace"))
    if expected is not None and expected not in data:
        print("CHYBA: očekávaná odpověď nebyla nalezena:", expected)
        return None
    return data


def main():
    ap = argparse.ArgumentParser(description=f"OpenVusion RF Probe v{FW_VERSION} USB/RF-control acceptance test")
    ap.add_argument("port", nargs="?")
    ap.add_argument(
        "--basic-only",
        action="store_true",
        help="otestuje jen PING/INFO; nezkouší nové STEP/RSSI/WATCH příkazy",
    )
    args = ap.parse_args()

    port = args.port
    matches = discover()

    if port is None:
        if len(matches) != 1:
            print(
                f"CHYBA: v{FW_VERSION} očekává právě JEDEN 2fe3:0001 CDC port; "
                f"nalezeno {len(matches)}."
            )
            for p in matches:
                print(
                    f"  {p.device} product={p.product!r} "
                    f"description={p.description!r} SN={p.serial_number!r}"
                )
            return 2
        p = matches[0]
        port = p.device
        print(
            "Auto-detected:", p.device,
            "product=", repr(p.product),
            "description=", repr(p.description),
            "SN=", repr(p.serial_number),
        )

    print("Otevírám:", port)
    with serial.Serial(
        port,
        115200,
        timeout=0.10,
        write_timeout=2.0,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    ) as ser:
        try:
            ser.dtr = True
        except Exception as exc:
            print("VAROVÁNÍ DTR:", repr(exc))
        try:
            ser.rts = False
        except Exception:
            pass

        time.sleep(0.35)
        startup = read_for(ser, 0.20)
        print("STARTUP raw:", repr(startup))
        if startup:
            print(f"CHYBA: v{FW_VERSION} nemá posílat unsolicited startup data.")
            print(startup.decode("utf-8", errors="replace"))
            return 3

        if send(ser, "PING", f"PONG v{FW_VERSION}".encode()) is None:
            return 4
        info = send(ser, "INFO", f"FW=OpenVusion_RF_Probe_v{FW_VERSION}".encode(), 1.0)
        if info is None:
            return 5
        required_info = [b"USB_CDC_COUNT=1", b"RF_TX=DISABLED_BY_DESIGN", b"STEP_MHZ=", b"RSSI_MODE="]
        missing = [x for x in required_info if x not in info]
        if missing:
            print("CHYBA: INFO neobsahuje očekávané položky:", missing)
            return 6

        if args.basic_only:
            print(f"PASS: OpenVusion RF Probe v{FW_VERSION} základní USB CDC test funguje.")
            return 0

        # Feature acceptance. Every changed setting is restored so the probe
        # leaves the test in the normal v0.7 defaults.
        if send(ser, "STEP 5", b"OK STEP_MHZ=5") is None:
            return 7
        if send(ser, "STEP 1", b"OK STEP_MHZ=1") is None:
            return 8
        if send(ser, "RSSI MODE MAX", b"OK RSSI_MODE=MAX") is None:
            return 9
        if send(ser, "RSSI MODE LAST", b"OK RSSI_MODE=LAST") is None:
            return 10

        watch = send(ser, "WATCH START 2453 25", b"OK WATCH=ON FREQ=2453 PERIOD_MS=25", 0.7)
        if watch is None:
            return 11
        # The same read window should contain at least one focused sample.
        if b"RSSI," not in watch:
            extra = read_for(ser, 0.7)
            print("WATCH extra:", repr(extra))
            watch += extra
        if b"RSSI," not in watch:
            print("CHYBA: WATCH nepřinesl RSSI sample")
            send(ser, "WATCH STOP", b"OK WATCH=OFF")
            return 12
        if send(ser, "WATCH STOP", b"OK WATCH=OFF") is None:
            return 13

        print(f"PASS: OpenVusion RF Probe v{FW_VERSION} USB + STEP + RSSI MODE + WATCH fungují.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
