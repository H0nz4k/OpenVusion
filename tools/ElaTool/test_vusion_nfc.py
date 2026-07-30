from elatec_uid_tool.protocol import SimpleProtocolClient


PORT = "COM6"


def crc_a(data: bytes) -> bytes:
    """
    ISO/IEC 14443-A CRC.
    Výsledek vrací little-endian, tedy v pořadí posílaném na RF.
    """
    crc = 0x6363

    for value in data:
        value ^= crc & 0xFF
        value ^= (value << 4) & 0xFF

        crc = (
            (crc >> 8)
            ^ (value << 8)
            ^ (value << 3)
            ^ (value >> 4)
        ) & 0xFFFF

    return crc.to_bytes(2, "little")


def transceive(
    client: SimpleProtocolClient,
    command: bytes,
    max_rx_bytes: int = 0xFF,
    timeout_ms: int = 255,
) -> bytes | None:
    frame = command + crc_a(command)

    print()
    print(f"NFC command: {command.hex(' ').upper()}")
    print(f"CRC_A:       {frame[-2:].hex(' ').upper()}")
    print(f"RF TX:       {frame.hex(' ').upper()}")

    response = client.iso14443_3_tdx(
        frame,
        max_rx_bytes=max_rx_bytes,
        timeout_ms=timeout_ms,
    )

    if response is None:
        print("RF RX:       bez odpovědi / Result=false")
        return None

    print(f"RF RX:       {response.hex(' ').upper()}")
    print(f"RX length:   {len(response)} bajtů")

    return response


def main() -> None:
    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()

        if tag is None:
            raise RuntimeError("NFC tag nebyl nalezen.")

        print(f"TagType: 0x{tag.tag_type:02X}")
        print(f"UID:     {tag.id_hex}")
        print(f"Bits:    {tag.id_bit_count}")

        # NTAG GET_VERSION
        version = transceive(client, bytes.fromhex("60"))

        if version is not None:
            print()
            print("GET_VERSION data:")
            print(version.hex(" ").upper())

            expected = bytes.fromhex("00 04 04 05 02 02 13 03")

            if version.startswith(expected):
                print("Odpověď odpovídá NTAG I²C Plus 1K.")
            else:
                print("Odpověď se liší od očekávaného GET_VERSION.")

        # Bezpečné čtení stránek 0 až 3.
        read_0 = transceive(client, bytes.fromhex("30 00"))

        if read_0 is not None:
            print()
            print("READ 00 data:")
            print(read_0.hex(" ").upper())


if __name__ == "__main__":
    main()