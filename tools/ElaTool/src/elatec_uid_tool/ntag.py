from __future__ import annotations

from dataclasses import dataclass

from .protocol import SerialCommunicationError, SimpleProtocolClient


def crc_a(data: bytes) -> bytes:
    """Vypočítá ISO/IEC 14443-A CRC v pořadí bajtů posílaném po RF."""
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


def verify_and_strip_crc_a(frame: bytes) -> bytes:
    """Ověří CRC_A odpovědi a vrátí pouze datovou část."""
    if len(frame) < 3:
        raise SerialCommunicationError(
            f"RF odpověď je příliš krátká: {frame.hex(' ').upper()}"
        )

    data = frame[:-2]
    received_crc = frame[-2:]
    expected_crc = crc_a(data)

    if received_crc != expected_crc:
        raise SerialCommunicationError(
            "Neplatné CRC_A odpovědi: "
            f"data={data.hex(' ').upper()}, "
            f"přijato={received_crc.hex(' ').upper()}, "
            f"očekáváno={expected_crc.hex(' ').upper()}"
        )

    return data


@dataclass(frozen=True)
class NtagVersion:
    vendor_id: int
    product_type: int
    product_subtype: int
    major_version: int
    minor_version: int
    storage_size: int
    protocol_type: int
    raw: bytes

    @classmethod
    def parse(cls, data: bytes) -> "NtagVersion":
        if len(data) != 8:
            raise SerialCommunicationError(
                f"GET_VERSION má mít 8 datových bajtů, přišlo {len(data)}."
            )

        return cls(
            vendor_id=data[1],
            product_type=data[2],
            product_subtype=data[3],
            major_version=data[4],
            minor_version=data[5],
            storage_size=data[6],
            protocol_type=data[7],
            raw=data,
        )

    @property
    def is_ntag_i2c_plus_1k(self) -> bool:
        return self.raw == bytes.fromhex("00 04 04 05 02 02 13 03")


class NtagI2CPlus:
    """Malá čtecí vrstva pro NTAG I²C Plus přes ELATEC TWN4."""

    def __init__(
        self,
        client: SimpleProtocolClient,
        *,
        max_rx_bytes: int = 0xFF,
        timeout_ms: int = 255,
    ) -> None:
        self.client = client
        self.max_rx_bytes = max_rx_bytes
        self.timeout_ms = timeout_ms

    def transceive(self, command: bytes) -> bytes:
        """Pošle NFC příkaz, přidá CRC_A a ověří CRC_A odpovědi."""
        if not command:
            raise ValueError("NFC příkaz nesmí být prázdný.")

        tx_frame = command + crc_a(command)
        rx_frame = self.client.iso14443_3_tdx(
            tx_frame,
            max_rx_bytes=self.max_rx_bytes,
            timeout_ms=self.timeout_ms,
        )

        if rx_frame is None:
            raise SerialCommunicationError(
                f"Tag neodpověděl na příkaz {command.hex(' ').upper()}."
            )

        # Type-2 Tag může vrátit krátký NAK bez CRC.
        if len(rx_frame) == 1:
            nak = rx_frame[0] & 0x0F
            descriptions = {
                0x00: "invalid argument",
                0x01: "CRC/parity error",
                0x03: "invalid address or command range",
                0x04: "EEPROM write error",
                0x05: "EEPROM write error",
            }
            description = descriptions.get(nak, f"NAK 0x{nak:X}")
            raise SerialCommunicationError(
                f"Tag odmítl příkaz {command.hex(' ').upper()}: {description}."
            )

        return verify_and_strip_crc_a(rx_frame)

    def get_version(self) -> NtagVersion:
        """NTAG GET_VERSION (0x60)."""
        return NtagVersion.parse(self.transceive(b"\x60"))

    def read_block(self, start_page: int) -> bytes:
        """READ (0x30): načte 4 stránky, tedy 16 bajtů."""
        if not 0 <= start_page <= 0xFF:
            raise ValueError("start_page musí být 0 až 255.")

        data = self.transceive(bytes((0x30, start_page)))

        if len(data) != 16:
            raise SerialCommunicationError(
                f"READ od stránky 0x{start_page:02X} měl vrátit 16 bajtů, "
                f"přišlo {len(data)}."
            )

        return data

    def read_page(self, page: int) -> bytes:
        """Načte jednu 4bajtovou stránku pomocí zarovnaného READ bloku."""
        if not 0 <= page <= 0xFF:
            raise ValueError("page musí být 0 až 255.")

        block_start = page & ~0x03
        block = self.read_block(block_start)
        offset = (page - block_start) * 4
        return block[offset : offset + 4]

    def read_pages(self, start_page: int, count: int) -> dict[int, bytes]:
        """Načte zadaný počet stránek a vrátí je podle čísla stránky."""
        if count < 1:
            raise ValueError("count musí být alespoň 1.")
        if start_page + count - 1 > 0xFF:
            raise ValueError("Požadovaný rozsah překračuje stránku 255.")

        result: dict[int, bytes] = {}
        current = start_page

        while current < start_page + count:
            block_start = current & ~0x03
            block = self.read_block(block_start)

            for index in range(4):
                page = block_start + index
                if start_page <= page < start_page + count:
                    offset = index * 4
                    result[page] = block[offset : offset + 4]

            current = block_start + 4

        return result

    def read_configuration_registers(self) -> dict[int, bytes]:
        """Přečte konfigurační registry NTAG I²C Plus přes NFC.

        Používá pouze read-only příkaz READ (0x30).

        Vrací:
            0xE8: NC_REG, LAST_NDEF_BLOCK, SRAM_MIRROR_BLOCK, WDT_LS
            0xE9: WDT_MS, I2C_CLOCK_STR, REG_LOCK, RFU
        """
        block = self.read_block(0xE8)

        return {
            0xE8: block[0:4],
            0xE9: block[4:8],
        }

