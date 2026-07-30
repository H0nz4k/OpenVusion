from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SimpleProtocolClient


PORT = "COM6"


def main() -> None:
    print(f"Otevírám čtečku na {PORT}...")

    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError("NFC tag nebyl nalezen. Přilož štítek ke čtečce.")

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
        print("Čtení dokončeno. Nebyl proveden žádný zápis do tagu.")


if __name__ == "__main__":
    main()
