from datetime import datetime
from pathlib import Path

from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SimpleProtocolClient


PORT = "COM6"
OUTPUT_ROOT = Path("captures") / "nfc"


def main() -> None:
    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError("NFC tag nebyl nalezen.")

        print(f"TagType: 0x{tag.tag_type:02X}")
        print(f"UID:     {tag.id_hex}")
        print(f"Bits:    {tag.id_bit_count}")
        print()
        print("Čtu EEPROM stránky 0x00–0xE1...")

        ntag = NtagI2CPlus(client)
        dump = ntag.dump(tag.id_hex)

        print(f"Načteno: {len(dump.pages)} stránek / {len(dump.binary)} bajtů")
        print()
        print("ASCII náhled:")
        print(dump.ascii_preview())
        print()

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = OUTPUT_ROOT / timestamp
        paths = dump.save(output_dir)
        print("Uloženo:")
        for kind, path in paths.items():
            print(f"  {kind.upper():4s}: {path.resolve()}")


if __name__ == "__main__":
    main()
