from __future__ import annotations

import sys
from pathlib import Path


PORT = "COM6"

# Projekt používá src-layout:
# elaUIDtool/
# ├── read_ntag_configuration.py
# └── src/
#     └── elatec_uid_tool/
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if not SRC_DIR.exists():
    raise RuntimeError(f"Nenalezen adresář src: {SRC_DIR}")

sys.path.insert(0, str(SRC_DIR))

from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SimpleProtocolClient


def main() -> None:
    print(f"Projekt:          {PROJECT_ROOT}")
    print(f"Python balíčky:   {SRC_DIR}")
    print(f"Otevírám čtečku:  {PORT}")

    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError(
                "NFC tag nebyl nalezen. Přilož štítek ke čtečce."
            )

        print(f"UID:      {tag.id_hex}")
        print(f"TagType:  0x{tag.tag_type:02X}")
        print(f"ID bits:  {tag.id_bit_count}")

        ntag = NtagI2CPlus(client)

        version = ntag.get_version()
        print()
        print("GET_VERSION")
        print("-----------")
        print(version.raw.hex(" ").upper())

        print()
        print("NTAG configuration registers")
        print("============================")

        config = ntag.read_configuration_registers()

        for page, data in config.items():
            print(f"0x{page:02X}: {data.hex(' ').upper()}")

        print()
        print("Hotovo. Nebyl proveden žádný zápis do tagu.")


if __name__ == "__main__":
    main()
