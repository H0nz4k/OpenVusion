from __future__ import annotations

import sys
import time
from pathlib import Path


PORT = "COM6"
SAMPLE_COUNT = 3
SAMPLE_DELAY_SECONDS = 1.0

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if not SRC_DIR.exists():
    raise RuntimeError(f"Nenalezen adresář src: {SRC_DIR}")

sys.path.insert(0, str(SRC_DIR))

from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SerialCommunicationError, SimpleProtocolClient


def read_session_registers(ntag: NtagI2CPlus) -> bytes:
    """Přečte stránky 0xEC–0xED pomocí read-only FAST_READ.

    Příkaz:
        3A EC ED

    Vrací přesně osm bajtů:
        0: NC_REG
        1: LAST_NDEF_BLOCK
        2: SRAM_MIRROR_BLOCK
        3: WDT_LS
        4: WDT_MS
        5: I2C_CLOCK_STR
        6: NS_REG
        7: RFU
    """
    data = ntag.transceive(bytes((0x3A, 0xEC, 0xED)))

    if len(data) != 8:
        raise SerialCommunicationError(
            "FAST_READ 0xEC–0xED měl vrátit 8 datových bajtů, "
            f"přišlo {len(data)}: {data.hex(' ').upper()}"
        )

    return data


def format_bits(value: int) -> str:
    return f"{value:08b}"


def print_registers(data: bytes, sample_number: int) -> None:
    names = (
        "NC_REG",
        "LAST_NDEF_BLOCK",
        "SRAM_MIRROR_BLOCK",
        "WDT_LS",
        "WDT_MS",
        "I2C_CLOCK_STR",
        "NS_REG",
        "RFU",
    )

    print()
    print(f"Session registry sample #{sample_number}")
    print("--------------------------------")
    print(f"0xEC: {data[0:4].hex(' ').upper()}")
    print(f"0xED: {data[4:8].hex(' ').upper()}")
    print()

    for index, (name, value) in enumerate(zip(names, data)):
        page = 0xEC if index < 4 else 0xED
        offset = index if index < 4 else index - 4
        print(
            f"0x{page:02X}[{offset}]  "
            f"{name:18s} = 0x{value:02X}  ({format_bits(value)})"
        )


def print_changes(previous: bytes, current: bytes) -> None:
    changes = []

    for index, (old, new) in enumerate(zip(previous, current)):
        if old != new:
            changes.append((index, old, new))

    if not changes:
        print("Změna proti předchozímu vzorku: žádná")
        return

    print("Změny proti předchozímu vzorku:")

    for index, old, new in changes:
        page = 0xEC if index < 4 else 0xED
        offset = index if index < 4 else index - 4
        print(
            f"  0x{page:02X}[{offset}]: "
            f"0x{old:02X} -> 0x{new:02X}"
        )


def main() -> None:
    print(f"Projekt:          {PROJECT_ROOT}")
    print(f"Python balíčky:   {SRC_DIR}")
    print(f"Otevírám čtečku:  {PORT}")
    print("Režim:            pouze READ / FAST_READ")

    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()

        if tag is None:
            raise RuntimeError(
                "NFC tag nebyl nalezen. Přilož štítek ke čtečce."
            )

        print(f"UID:              {tag.id_hex}")
        print(f"TagType:          0x{tag.tag_type:02X}")
        print(f"ID bits:          {tag.id_bit_count}")

        ntag = NtagI2CPlus(client)
        version = ntag.get_version()

        print()
        print("GET_VERSION")
        print("-----------")
        print(version.raw.hex(" ").upper())

        previous: bytes | None = None

        for sample_number in range(1, SAMPLE_COUNT + 1):
            current = read_session_registers(ntag)
            print_registers(current, sample_number)

            if previous is not None:
                print()
                print_changes(previous, current)

            previous = current

            if sample_number < SAMPLE_COUNT:
                time.sleep(SAMPLE_DELAY_SECONDS)

        print()
        print("Hotovo. Nebyl proveden žádný zápis do tagu.")


if __name__ == "__main__":
    main()
