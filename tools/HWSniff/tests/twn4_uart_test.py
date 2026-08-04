#!/usr/bin/env python3
"""Jednoduchy UART terminal/sniffer pro ELATEC TWN4 na Raspberry Pi.

Pouziva pouze standardni knihovnu Pythonu (neni potreba pyserial).
Vychozi nastaveni: /dev/serial0, 9600 baud, 8N1, bez flow control.

Pred spustenim zastav sluzbu (port je exclusive):
  sudo systemctl stop hwsniff

"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import select
import sys
import termios
import time


BAUD_RATES = {
    rate: getattr(termios, f"B{rate}")
    for rate in (
        50, 75, 110, 134, 150, 200, 300, 600, 1200, 1800, 2400,
        4800, 9600, 19200, 38400, 57600, 115200, 230400,
    )
    if hasattr(termios, f"B{rate}")
}


def parse_hex(value: str) -> bytes:
    cleaned = value.replace("0x", "").replace(",", " ").replace(":", " ")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "HEX musi byt napr. '02 10 FF 0D 0A'"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cteni a zakladni testovani ELATEC TWN4 pres UART.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-p", "--port", default="/dev/serial0", help="UART zarizeni")
    parser.add_argument("-b", "--baud", type=int, default=9600, help="baudrate")
    parser.add_argument(
        "--parity", choices=("N", "E", "O"), default="N",
        help="parita: N=zadna, E=suda, O=licha",
    )
    parser.add_argument("--stopbits", choices=(1, 2), type=int, default=1)
    parser.add_argument(
        "-m", "--mode", choices=("both", "hex", "ascii"), default="both",
        help="format prijatych dat",
    )
    parser.add_argument(
        "--chunk", type=int, default=256, help="maximum bajtu v jednom vypisu"
    )
    parser.add_argument(
        "--duration", type=float, default=0,
        help="automaticky skoncit po N sekundach; 0 = bez omezeni",
    )
    parser.add_argument(
        "--send-text", help="po otevreni odeslat text (escape sekvence napr. \\r\\n)"
    )
    parser.add_argument(
        "--send-hex", type=parse_hex, help="po otevreni odeslat bajty, napr. '02 FF 0D'"
    )
    parser.add_argument("--rtscts", action="store_true", help="RTS/CTS flow control")
    parser.add_argument("--xonxoff", action="store_true", help="XON/XOFF flow control")
    return parser.parse_args()


def configure_uart(fd: int, args: argparse.Namespace) -> None:
    if args.baud not in BAUD_RATES:
        supported = ", ".join(str(x) for x in sorted(BAUD_RATES))
        raise ValueError(f"Nepodporovany baudrate {args.baud}. Dostupne: {supported}")

    attrs = termios.tcgetattr(fd)

    # iflag: zadne preklady CR/LF, kontrola parity ani SW flow control.
    attrs[0] = termios.IXON | termios.IXOFF if args.xonxoff else 0
    attrs[1] = 0  # oflag: zadne zmeny vystupu
    attrs[3] = 0  # lflag: raw rezim, bez echo a canonical zpracovani

    cflag = termios.CLOCAL | termios.CREAD | termios.CS8
    if args.stopbits == 2:
        cflag |= termios.CSTOPB
    if args.parity == "E":
        cflag |= termios.PARENB
    elif args.parity == "O":
        cflag |= termios.PARENB | termios.PARODD
    if args.rtscts:
        if not hasattr(termios, "CRTSCTS"):
            raise ValueError("RTS/CTS neni na tomto systemu podporovano")
        cflag |= termios.CRTSCTS
    attrs[2] = cflag

    attrs[4] = BAUD_RATES[args.baud]  # ispeed
    attrs[5] = BAUD_RATES[args.baud]  # ospeed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0

    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)


def decode_escaped_text(value: str) -> bytes:
    # Umoznuje zadat z prikazove radky napr. 'STATUS\\r\\n'.
    return value.encode("utf-8").decode("unicode_escape").encode("latin1")


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data)


def show_packet(data: bytes, mode: str) -> None:
    stamp = dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if mode == "hex":
        print(f"[{stamp}] RX {len(data):4d} B | {data.hex(' ').upper()}", flush=True)
    elif mode == "ascii":
        text = data.decode("utf-8", errors="backslashreplace")
        print(f"[{stamp}] RX {len(data):4d} B | {text!r}", flush=True)
    else:
        print(
            f"[{stamp}] RX {len(data):4d} B | "
            f"HEX: {data.hex(' ').upper()} | ASCII: {printable(data)}",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    if args.chunk < 1:
        print("CHYBA: --chunk musi byt alespon 1", file=sys.stderr)
        return 2

    flags = os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
    try:
        fd = os.open(args.port, flags)
    except PermissionError:
        print(
            f"CHYBA: Nemam opravneni k {args.port}. "
            "Pridej uzivatele do skupiny dialout: sudo usermod -aG dialout $USER",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"CHYBA: Nelze otevrit {args.port}: {exc}", file=sys.stderr)
        return 1

    try:
        configure_uart(fd, args)
        print(
            f"Otevreno {args.port}: {args.baud} baud, 8{args.parity}{args.stopbits}, "
            f"RTS/CTS={'ano' if args.rtscts else 'ne'}, "
            f"XON/XOFF={'ano' if args.xonxoff else 'ne'}"
        )
        print("Cekam na data; ukonceni Ctrl+C. Priloz kartu ke ctecce.\n")

        tx = b""
        if args.send_text is not None:
            tx += decode_escaped_text(args.send_text)
        if args.send_hex is not None:
            tx += args.send_hex
        if tx:
            os.write(fd, tx)
            print(f"TX {len(tx)} B | {tx.hex(' ').upper()} | {printable(tx)}\n")

        started = time.monotonic()
        while True:
            if args.duration and time.monotonic() - started >= args.duration:
                break
            readable, _, _ = select.select([fd], [], [], 0.25)
            if not readable:
                continue
            try:
                data = os.read(fd, args.chunk)
            except BlockingIOError:
                continue
            if data:
                show_packet(data, args.mode)

    except KeyboardInterrupt:
        print("\nUkonceno.")
    except (OSError, ValueError, termios.error) as exc:
        print(f"CHYBA UART: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(fd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
