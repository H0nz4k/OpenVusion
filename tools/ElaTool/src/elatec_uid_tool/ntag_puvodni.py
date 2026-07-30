from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import math
import re
from collections import Counter

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



@dataclass(frozen=True)
class NtagDataBlock:
    start_page: int
    end_page: int
    data: bytes
    kind: str
    notes: tuple[str, ...]

    @property
    def byte_count(self) -> int:
        return len(self.data)

    @property
    def entropy(self) -> float:
        if not self.data:
            return 0.0
        counts = Counter(self.data)
        total = len(self.data)
        return -sum(
            (count / total) * math.log2(count / total)
            for count in counts.values()
        )

    @property
    def ascii_preview(self) -> str:
        return "".join(
            chr(value) if 32 <= value <= 126 else "."
            for value in self.data
        )


@dataclass(frozen=True)
class NtagAnalysis:
    uid: str
    version: bytes
    blocks: tuple[NtagDataBlock, ...]
    nonzero_pages: tuple[int, ...]
    related_values: tuple[str, ...]
    observations: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schema": 1,
            "uid": self.uid,
            "get_version": self.version.hex(" ").upper(),
            "nonzero_pages": [f"0x{page:02X}" for page in self.nonzero_pages],
            "related_values": list(self.related_values),
            "observations": list(self.observations),
            "blocks": [
                {
                    "range": f"0x{block.start_page:02X}-0x{block.end_page:02X}",
                    "start_page": block.start_page,
                    "end_page": block.end_page,
                    "byte_count": block.byte_count,
                    "entropy_bits_per_byte": round(block.entropy, 4),
                    "kind": block.kind,
                    "notes": list(block.notes),
                    "hex": block.data.hex(" ").upper(),
                    "ascii_preview": block.ascii_preview,
                }
                for block in self.blocks
            ],
        }

    def to_text(self) -> str:
        lines = [
            "NTAG dump analysis",
            "==================",
            "",
            f"UID:         {self.uid}",
            f"GET_VERSION: {self.version.hex(' ').upper()}",
            f"Non-zero pages: {len(self.nonzero_pages)}",
            "",
            "OBSERVATIONS",
            "------------",
        ]
        lines.extend(f"- {item}" for item in self.observations or ("No notable observations.",))
        lines.extend(["", "DATA BLOCKS", "-----------"])

        for index, block in enumerate(self.blocks, start=1):
            lines.extend([
                "",
                f"Block #{index}: 0x{block.start_page:02X}-0x{block.end_page:02X}",
                f"Type:       {block.kind}",
                f"Bytes:      {block.byte_count}",
                f"Entropy:    {block.entropy:.4f} bits/byte",
                f"ASCII:      {block.ascii_preview}",
                f"Hex:        {block.data.hex(' ').upper()}",
            ])
            if block.notes:
                lines.append("Notes:")
                lines.extend(f"  - {note}" for note in block.notes)

        if self.related_values:
            lines.extend(["", "RELATED VALUES", "--------------"])
            lines.extend(f"- {item}" for item in self.related_values)

        lines.append("")
        return "\n".join(lines)

    def save(self, directory: str | Path, stem: str = "analysis") -> dict[str, Path]:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{stem}.json"
        txt_path = output_dir / f"{stem}.txt"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        txt_path.write_text(self.to_text(), encoding="utf-8")
        return {"json": json_path, "txt": txt_path}


@dataclass(frozen=True)
class NtagDump:
    uid: str
    version: bytes
    start_page: int
    end_page: int
    pages: dict[int, bytes]
    created_at: str

    @property
    def binary(self) -> bytes:
        return b"".join(self.pages[page] for page in range(self.start_page, self.end_page + 1))

    def ascii_preview(self) -> str:
        return "".join(
            chr(value) if 32 <= value <= 126 else "."
            for value in self.binary
        )

    def to_dict(self) -> dict:
        return {
            "schema": 1,
            "created_at": self.created_at,
            "uid": self.uid,
            "get_version": self.version.hex(" ").upper(),
            "range": {
                "start_page": self.start_page,
                "end_page": self.end_page,
                "page_count": len(self.pages),
                "byte_count": len(self.binary),
            },
            "pages": {
                f"{page:03d}": data.hex(" ").upper()
                for page, data in self.pages.items()
            },
            "ascii_preview": self.ascii_preview(),
        }

    def analyze(self) -> NtagAnalysis:
        """Analyze a dump without modifying the tag."""
        nonzero_pages = tuple(
            page for page, data in self.pages.items()
            if any(value != 0x00 for value in data)
        )

        ranges: list[tuple[int, int]] = []
        if nonzero_pages:
            start = previous = nonzero_pages[0]
            for page in nonzero_pages[1:]:
                if page == previous + 1:
                    previous = page
                else:
                    ranges.append((start, previous))
                    start = previous = page
            ranges.append((start, previous))

        blocks: list[NtagDataBlock] = []
        observations: list[str] = []
        related: list[str] = []
        full_binary = self.binary

        for start_page, end_page in ranges:
            data = b"".join(
                self.pages[page]
                for page in range(start_page, end_page + 1)
            )
            notes: list[str] = []
            kind = "unknown binary data"

            if start_page <= 0x04 <= end_page and b"\x03" in data:
                kind = "NDEF / NFC Forum data"
                notes.append("Contains NDEF Message TLV marker 0x03.")
                if b"\xFE" in data:
                    notes.append("Contains Terminator TLV marker 0xFE.")

            printable = sum(32 <= value <= 126 for value in data)
            if data and printable / len(data) >= 0.60:
                notes.append("High proportion of printable ASCII bytes.")
                if kind == "unknown binary data":
                    kind = "text-like data"

            blocks.append(NtagDataBlock(
                start_page=start_page,
                end_page=end_page,
                data=data,
                kind=kind,
                notes=tuple(notes),
            ))

        ascii_runs: list[str] = []
        current = bytearray()
        for value in full_binary:
            if 32 <= value <= 126:
                current.append(value)
            else:
                if len(current) >= 4:
                    ascii_runs.append(current.decode("ascii"))
                current.clear()
        if len(current) >= 4:
            ascii_runs.append(current.decode("ascii"))

        for run in ascii_runs:
            for match in re.finditer(r"(?i)(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])", run):
                hex_id = match.group(0).upper()
                raw_id = bytes.fromhex(hex_id)
                reversed_id = raw_id[::-1]
                if reversed_id in full_binary:
                    related.append(
                        f"ASCII ID {hex_id} has a little-endian binary copy "
                        f"{reversed_id.hex(' ').upper()} elsewhere in EEPROM."
                    )

        if ascii_runs:
            observations.append(
                "Printable ASCII strings: " + ", ".join(repr(item) for item in ascii_runs)
            )
        if len(blocks) > 1:
            observations.append(f"Found {len(blocks)} separate non-zero data regions.")
        if any(block.start_page == 0x30 and block.end_page >= 0x37 for block in blocks):
            observations.append(
                "Pages 0x30-0x37 form a separate 32-byte application/manufacturer data block."
            )

        return NtagAnalysis(
            uid=self.uid,
            version=self.version,
            blocks=tuple(blocks),
            nonzero_pages=nonzero_pages,
            related_values=tuple(dict.fromkeys(related)),
            observations=tuple(observations),
        )

    def save(self, directory: str | Path, stem: str | None = None) -> dict[str, Path]:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)

        base = stem or f"ntag-{self.uid.lower()}-{self.start_page:02x}-{self.end_page:02x}"
        bin_path = output_dir / f"{base}.bin"
        json_path = output_dir / f"{base}.json"
        txt_path = output_dir / f"{base}.txt"

        bin_path.write_bytes(self.binary)
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        lines = [
            "NTAG I²C Plus dump",
            "==================",
            "",
            f"Created:     {self.created_at}",
            f"UID:         {self.uid}",
            f"GET_VERSION: {self.version.hex(' ').upper()}",
            f"Pages:       0x{self.start_page:02X}–0x{self.end_page:02X}",
            f"Bytes:       {len(self.binary)}",
            "",
            "PAGE DUMP",
            "---------",
        ]
        for page, data in self.pages.items():
            ascii_part = "".join(chr(value) if 32 <= value <= 126 else "." for value in data)
            lines.append(
                f"{page:03d} / 0x{page:02X}: "
                f"{data.hex(' ').upper():11s}  |{ascii_part}|"
            )

        lines.extend([
            "",
            "ASCII PREVIEW",
            "-------------",
            self.ascii_preview(),
            "",
        ])
        txt_path.write_text("\n".join(lines), encoding="utf-8")

        return {"bin": bin_path, "json": json_path, "txt": txt_path}


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

        # ISO14443-A Type 2 Tag může při chybě vrátit krátký 4bitový NAK,
        # který TWN4 předá jako jediný bajt bez CRC. Hodnota 0x03 obvykle
        # znamená invalid argument / neplatný rozsah příkazu.
        if len(rx_frame) == 1:
            nak = rx_frame[0] & 0x0F
            nak_names = {
                0x00: "NAK: invalid argument",
                0x01: "NAK: CRC/parity error",
                0x04: "NAK: EEPROM write error",
                0x05: "NAK: EEPROM write error",
                0x03: "NAK: invalid address or command range",
            }
            description = nak_names.get(nak, f"NAK 0x{nak:X}")
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
        """Načte zadaný počet stránek a vrátí je podle čísla stránky.

        READ (0x30) vždy vrací čtyři stránky, ale počáteční stránka nemusí být
        zarovnaná na násobek čtyř. Poslední blok proto při konci paměti
        posuneme zpět tak, aby nepřekročil požadovanou koncovou stránku.
        """
        if count < 1:
            raise ValueError("count musí být alespoň 1.")

        end_page = start_page + count - 1
        if end_page > 0xFF:
            raise ValueError("Požadovaný rozsah překračuje stránku 255.")

        result: dict[int, bytes] = {}
        current = start_page

        while current <= end_page:
            # Běžně čteme od aktuální stránky. Pokud by čtyřstránkový READ
            # přesáhl konec požadovaného rozsahu, posuneme poslední čtení
            # zpět. Např. pro konec 0xE1 čteme poslední blok od 0xDE,
            # tedy stránky 0xDE–0xE1, nikoli neplatné 0xE0–0xE3.
            block_start = current
            if block_start + 3 > end_page:
                block_start = max(start_page, end_page - 3)

            block = self.read_block(block_start)

            for index in range(4):
                page = block_start + index
                if start_page <= page <= end_page:
                    offset = index * 4
                    result[page] = block[offset : offset + 4]

            next_page = max(result) + 1
            if next_page <= current:
                raise SerialCommunicationError(
                    "Čtení stránek se neposunulo; přerušuji kvůli ochraně před smyčkou."
                )
            current = next_page

        return dict(sorted(result.items()))


    def dump(
        self,
        uid: str,
        *,
        start_page: int = 0x00,
        end_page: int = 0xE1,
    ) -> NtagDump:
        """Načte bezpečný EEPROM rozsah NTAG I²C Plus 1K.

        Výchozí konec 0xE1 odpovídá konci běžné uživatelské EEPROM oblasti.
        Speciální konfigurační, SRAM a session oblasti nejsou součástí tohoto
        výchozího dumpu a budou čteny samostatnými explicitními metodami.
        """
        if not 0 <= start_page <= 0xFF:
            raise ValueError("start_page musí být 0 až 255.")
        if not 0 <= end_page <= 0xFF:
            raise ValueError("end_page musí být 0 až 255.")
        if end_page < start_page:
            raise ValueError("end_page nesmí být menší než start_page.")

        version = self.get_version()
        pages = self.read_pages(start_page, end_page - start_page + 1)

        return NtagDump(
            uid=uid,
            version=version.raw,
            start_page=start_page,
            end_page=end_page,
            pages=pages,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
