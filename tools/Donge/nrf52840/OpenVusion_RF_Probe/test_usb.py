import argparse
import time

import serial
from serial.tools import list_ports

TARGET_VID = 0x2FE3
TARGET_PID = 0x0001

def discover():
    return [
        p for p in list_ports.comports()
        if p.vid == TARGET_VID and p.pid == TARGET_PID
    ]

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

def main():
    ap = argparse.ArgumentParser(
        description="OpenVusion RF Probe v0.6.1 USB acceptance test"
    )
    ap.add_argument("port", nargs="?")
    args = ap.parse_args()

    port = args.port
    matches = discover()

    if port is None:
        if len(matches) != 1:
            print(
                f"CHYBA: v0.6.1 očekává právě JEDEN 2fe3:0001 CDC port; "
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
            "Auto-detected:",
            p.device,
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

        # Allow pySerial to finish termios/raw/no-echo setup.
        time.sleep(0.35)

        startup = read_for(ser, 0.20)
        print("STARTUP raw:", repr(startup))
        if startup:
            print("CHYBA: v0.6.1 nemá posílat unsolicited startup data.")
            print(startup.decode("utf-8", errors="replace"))
            return 3

        for cmd, expected in (
            ("PING", b"PONG v0.6.1"),
            ("INFO", b"FW=OpenVusion_RF_Probe_v0.6.1"),
        ):
            print(f">>> {cmd}")
            try:
                sent = ser.write((cmd + "\r\n").encode("ascii"))
                ser.flush()
            except serial.SerialTimeoutException:
                print("CHYBA: WRITE TIMEOUT")
                return 4

            print("TX bytes:", sent)
            data = read_for(ser, 1.0)
            print("RX raw:", repr(data))
            if data:
                print(data.decode("utf-8", errors="replace"))

            if expected not in data:
                print("CHYBA: očekávaná odpověď nebyla nalezena:", expected)
                return 5

        print("PASS: OpenVusion RF Probe v0.6.1 USB CDC RX/TX funguje.")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
