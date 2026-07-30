from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SimpleProtocolClient


PORT = "COM6"


def main() -> None:
    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError("NFC tag nebyl nalezen.")

        print(f"TagType: 0x{tag.tag_type:02X}")
        print(f"UID:     {tag.id_hex}")
        print(f"Bits:    {tag.id_bit_count}")

        ntag = NtagI2CPlus(client)

        version = ntag.get_version()
        print()
        print("GET_VERSION")
        print(f"Raw:            {version.raw.hex(' ').upper()}")
        print(f"Vendor ID:      0x{version.vendor_id:02X}")
        print(f"Product type:   0x{version.product_type:02X}")
        print(f"Product subtype:0x{version.product_subtype:02X}")
        print(f"Version:        {version.major_version}.{version.minor_version}")
        print(f"Storage size:   0x{version.storage_size:02X}")
        print(f"Protocol type:  0x{version.protocol_type:02X}")
        print(
            "Identifikace:   "
            + (
                "NTAG I²C Plus 1K"
                if version.is_ntag_i2c_plus_1k
                else "jiná / zatím nerozpoznaná varianta"
            )
        )

        print()
        print("STRÁNKY 0–15")
        pages = ntag.read_pages(0, 16)
        for page, data in pages.items():
            print(f"{page:03d} / 0x{page:02X}: {data.hex(' ').upper()}")


if __name__ == "__main__":
    main()
