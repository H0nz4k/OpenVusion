from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_SIZE_BYTES,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from ..protocol import SimpleProtocolClient
from .checksums import ChecksumCandidate, evaluate_checksum_candidates
from .dump_loaders import load_application_block
from ..capture.models import safe_ascii_preview

CONFIRMED_NDEF_ID_HEX = "AA2CD0C9"
CONFIRMED_LE_PAGE_33 = bytes.fromhex("C9 D0 2C AA")


@dataclass
class ApplicationBlockReport:
    block: bytes
    start_page: int = EEPROM_WATCH_START_PAGE
    end_page: int = EEPROM_WATCH_END_PAGE
    source: str | None = None
    uid: str | None = None
    facts: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    checksum_candidates: list[ChecksumCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.block) != EEPROM_WATCH_SIZE_BYTES:
            raise ValueError(
                f"Application block musí mít přesně {EEPROM_WATCH_SIZE_BYTES} bajtů, "
                f"přišlo {len(self.block)}."
            )

    @property
    def pages(self) -> dict[int, bytes]:
        return {
            self.start_page + index: self.block[index * 4 : (index + 1) * 4]
            for index in range(8)
        }

    def to_dict(self) -> dict[str, Any]:
        page_33 = self.pages.get(0x33, b"")
        confirmed_le = page_33 == CONFIRMED_LE_PAGE_33
        matches = [c for c in self.checksum_candidates if c.matches]
        return {
            "schema": 1,
            "source": self.source,
            "uid": self.uid,
            "range": {
                "start_page": self.start_page,
                "end_page": self.end_page,
                "byte_count": len(self.block),
            },
            "raw_hex": self.block.hex(" ").upper(),
            "ascii_preview": safe_ascii_preview(self.block),
            "pages": {
                f"0x{page:02X}": data.hex(" ").upper()
                for page, data in self.pages.items()
            },
            "bytes": [
                {
                    "absolute_offset": index,
                    "page": self.start_page + (index // 4),
                    "offset_in_page": index % 4,
                    "value": value,
                    "hex": f"0x{value:02X}",
                }
                for index, value in enumerate(self.block)
            ],
            "zero_offsets": [i for i, v in enumerate(self.block) if v == 0],
            "ff_offsets": [i for i, v in enumerate(self.block) if v == 0xFF],
            "nonzero_offsets": [i for i, v in enumerate(self.block) if v not in (0, 0xFF)],
            "endian_views": self._endian_views(),
            "bit_stats": self._bit_stats(),
            "repeated_patterns": self._repeated_patterns(),
            "ndef_id": {
                "confirmed_value": CONFIRMED_NDEF_ID_HEX,
                "page_0x33_hex": page_33.hex(" ").upper(),
                "confirmed_little_endian_identifier_match": confirmed_le,
            },
            "checksum_matches": [asdict(item) for item in matches],
            "checksum_candidates_total": len(self.checksum_candidates),
            "facts": self.facts,
            "hypotheses": self.hypotheses,
        }

    def _endian_views(self) -> dict[str, Any]:
        views: dict[str, Any] = {"u16": [], "u32": []}
        for offset in range(0, len(self.block) - 1, 2):
            chunk = self.block[offset : offset + 2]
            views["u16"].append(
                {
                    "offset": offset,
                    "le": int.from_bytes(chunk, "little"),
                    "be": int.from_bytes(chunk, "big"),
                    "hex": chunk.hex(" ").upper(),
                }
            )
        for offset in range(0, len(self.block) - 3, 4):
            chunk = self.block[offset : offset + 4]
            views["u32"].append(
                {
                    "offset": offset,
                    "page": self.start_page + (offset // 4),
                    "le": int.from_bytes(chunk, "little"),
                    "be": int.from_bytes(chunk, "big"),
                    "hex": chunk.hex(" ").upper(),
                }
            )
        return views

    def _bit_stats(self) -> dict[str, Any]:
        ones = sum(bin(value).count("1") for value in self.block)
        total = len(self.block) * 8
        counts = Counter(self.block)
        return {
            "ones": ones,
            "zeros": total - ones,
            "ones_ratio": ones / total,
            "unique_byte_values": len(counts),
            "most_common": [
                {"value": f"0x{value:02X}", "count": count}
                for value, count in counts.most_common(5)
            ],
        }

    def _repeated_patterns(self) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        for size in (2, 4):
            seen: dict[bytes, list[int]] = {}
            for offset in range(0, len(self.block) - size + 1):
                chunk = self.block[offset : offset + size]
                seen.setdefault(chunk, []).append(offset)
            for chunk, offsets in seen.items():
                if len(offsets) >= 2 and chunk not in (b"\x00" * size, b"\xff" * size):
                    patterns.append(
                        {
                            "size": size,
                            "hex": chunk.hex(" ").upper(),
                            "offsets": offsets,
                            "count": len(offsets),
                        }
                    )
        patterns.sort(key=lambda item: (-item["count"], item["size"], item["hex"]))
        return patterns[:20]

    def to_text(self) -> str:
        data = self.to_dict()
        lines = [
            "Application Block Analysis 0x30–0x37",
            "====================================",
            "",
            f"Source: {self.source}",
            f"UID: {self.uid}",
            f"Raw: {data['raw_hex']}",
            f"ASCII: {data['ascii_preview']}",
            "",
            "Pages:",
        ]
        for page, hex_value in data["pages"].items():
            lines.append(f"  {page}: {hex_value}")
        lines.append("")
        ndef = data["ndef_id"]
        lines.append(
            "NDEF ID match: "
            + (
                "confirmed little-endian identifier match"
                if ndef["confirmed_little_endian_identifier_match"]
                else "not matched"
            )
        )
        lines.append(f"  expected: {ndef['confirmed_value']}")
        lines.append(f"  page 0x33: {ndef['page_0x33_hex']}")
        lines.append("")
        lines.append("Facts:")
        for fact in self.facts:
            lines.append(f"  - {fact}")
        lines.append("")
        lines.append("Hypotheses (not facts):")
        for item in self.hypotheses:
            lines.append(f"  - {item}")
        lines.append("")
        lines.append(
            f"Checksum candidate matches: {len(data['checksum_matches'])} "
            f"/ {data['checksum_candidates_total']} tests"
        )
        for item in data["checksum_matches"][:10]:
            lines.append(
                f"  - {item['algorithm']} {item['coverage']}: "
                f"0x{item['computed']:X} == 0x{item['expected']:X} "
                f"({item['note']})"
            )
        lines.append("")
        return "\n".join(lines)


def analyze_application_block(
    block: bytes,
    *,
    source: str | None = None,
    uid: str | None = None,
    ndef_id_hex: str = CONFIRMED_NDEF_ID_HEX,
) -> ApplicationBlockReport:
    if len(block) != EEPROM_WATCH_SIZE_BYTES:
        raise ValueError(
            f"Application block musí mít přesně {EEPROM_WATCH_SIZE_BYTES} bajtů, "
            f"přišlo {len(block)}."
        )

    report = ApplicationBlockReport(
        block=block,
        source=source,
        uid=uid,
        checksum_candidates=evaluate_checksum_candidates(block),
    )

    page_33 = report.pages[0x33]
    expected_le = bytes.fromhex(ndef_id_hex)[::-1]
    if page_33 == expected_le:
        report.facts.append(
            f"confirmed little-endian identifier match: "
            f"NDEF {ndef_id_hex} == page 0x33 {page_33.hex(' ').upper()}"
        )
    else:
        report.facts.append(
            f"page 0x33 {page_33.hex(' ').upper()} does not match "
            f"little-endian form of {ndef_id_hex}"
        )

    report.facts.append(
        f"block length {len(block)} B covering pages "
        f"0x{EEPROM_WATCH_START_PAGE:02X}–0x{EEPROM_WATCH_END_PAGE:02X}"
    )
    report.facts.append(
        f"zero bytes={len(report.to_dict()['zero_offsets'])}, "
        f"0xFF bytes={len(report.to_dict()['ff_offsets'])}, "
        f"other={len(report.to_dict()['nonzero_offsets'])}"
    )

    report.hypotheses.extend(
        [
            "Page 0x30 may encode a packed capability/header (A0 81 …) — unverified.",
            "Pages 0x31–0x32 all-0xFF may be unused/reserved — unverified.",
            "Trailing bytes on 0x37 may be a checksum/CRC — candidate only.",
            "Fields on 0x34–0x36 may include counters/version/flags — unverified.",
        ]
    )
    return report


def analyze_application_block_file(path: Path) -> ApplicationBlockReport:
    block, meta = load_application_block(path)
    return analyze_application_block(
        block,
        source=str(path),
        uid=meta.get("uid"),
    )


def read_application_block_from_tag(
    client: SimpleProtocolClient,
) -> tuple[bytes, str, bytes]:
    tag = client.search_tag()
    if tag is None:
        raise RuntimeError("NFC tag nebyl nalezen.")
    ntag = NtagI2CPlus(client)
    version = ntag.get_version()
    block = ntag.read_eeprom_range(
        EEPROM_WATCH_START_PAGE,
        EEPROM_WATCH_END_PAGE,
    )
    return block, tag.id_hex, version.raw


@dataclass
class ApplicationBlockComparison:
    sources: list[str]
    constant_offsets: list[int]
    variable_offsets: list[int]
    page_changes: dict[str, list[int]]
    byte_changes: list[dict[str, Any]]
    ndef_id_correlation: dict[str, Any]
    counter_candidates: list[dict[str, Any]]
    timestamp_candidates: list[dict[str, Any]]
    checksum_field_candidates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_text(self) -> str:
        lines = [
            "Application Block Comparison",
            "============================",
            "",
            f"Sources: {len(self.sources)}",
        ]
        for source in self.sources:
            lines.append(f"  - {source}")
        lines.append("")
        lines.append(f"Constant offsets: {self.constant_offsets}")
        lines.append(f"Variable offsets: {self.variable_offsets}")
        lines.append("")
        lines.append("Byte changes:")
        for item in self.byte_changes:
            lines.append(
                f"  offset {item['absolute_offset']} "
                f"(page 0x{item['page']:02X}[{item['offset_in_page']}]): "
                f"{item['values_hex']}"
            )
        lines.append("")
        lines.append(
            "NDEF ID correlation: "
            + str(self.ndef_id_correlation.get("summary"))
        )
        lines.append(
            f"Counter candidates: {len(self.counter_candidates)}"
        )
        lines.append(
            f"Timestamp candidates: {len(self.timestamp_candidates)}"
        )
        lines.append(
            f"Checksum field candidates: {len(self.checksum_field_candidates)}"
        )
        lines.append("")
        return "\n".join(lines)


def compare_application_blocks(
    blocks: list[tuple[str, bytes]],
) -> ApplicationBlockComparison:
    if len(blocks) < 2:
        raise ValueError("Porovnání vyžaduje alespoň dva bloky.")
    for source, block in blocks:
        if len(block) != EEPROM_WATCH_SIZE_BYTES:
            raise ValueError(
                f"{source}: očekáváno {EEPROM_WATCH_SIZE_BYTES} B, přišlo {len(block)}."
            )

    sources = [source for source, _ in blocks]
    data = [block for _, block in blocks]
    constant: list[int] = []
    variable: list[int] = []
    byte_changes: list[dict[str, Any]] = []

    for offset in range(EEPROM_WATCH_SIZE_BYTES):
        values = [block[offset] for block in data]
        if len(set(values)) == 1:
            constant.append(offset)
        else:
            variable.append(offset)
            byte_changes.append(
                {
                    "absolute_offset": offset,
                    "page": EEPROM_WATCH_START_PAGE + (offset // 4),
                    "offset_in_page": offset % 4,
                    "values": values,
                    "values_hex": [f"0x{value:02X}" for value in values],
                }
            )

    page_changes: dict[str, list[int]] = {}
    for page in range(EEPROM_WATCH_START_PAGE, EEPROM_WATCH_END_PAGE + 1):
        base = (page - EEPROM_WATCH_START_PAGE) * 4
        changed = [offset for offset in variable if base <= offset < base + 4]
        page_changes[f"0x{page:02X}"] = changed

    id_values = [block[12:16] for block in data]
    ndef_corr = {
        "page_0x33_values": [value.hex(" ").upper() for value in id_values],
        "all_equal": len(set(id_values)) == 1,
        "matches_confirmed_le": all(value == CONFIRMED_LE_PAGE_33 for value in id_values),
        "summary": (
            "identifier field constant across dumps"
            if len(set(id_values)) == 1
            else "identifier field differs across dumps"
        ),
    }

    counter_candidates: list[dict[str, Any]] = []
    timestamp_candidates: list[dict[str, Any]] = []
    for offset in range(0, EEPROM_WATCH_SIZE_BYTES - 1, 2):
        series = [
            int.from_bytes(block[offset : offset + 2], "little") for block in data
        ]
        if len(set(series)) == len(series) and series == sorted(series):
            counter_candidates.append(
                {
                    "offset": offset,
                    "endian": "little",
                    "width": 16,
                    "values": series,
                    "note": "strictly increasing across dumps — counter candidate",
                }
            )
        # crude timestamp heuristic: 32-bit LE in plausible unix-ish range
    for offset in range(0, EEPROM_WATCH_SIZE_BYTES - 3, 4):
        series32 = [
            int.from_bytes(block[offset : offset + 4], "little") for block in data
        ]
        if (
            len(set(series32)) == len(series32)
            and series32 == sorted(series32)
            and all(1_600_000_000 <= value <= 2_200_000_000 for value in series32)
        ):
            timestamp_candidates.append(
                {
                    "offset": offset,
                    "endian": "little",
                    "width": 32,
                    "values": series32,
                    "note": "increasing 32-bit values in loose unix range — weak candidate",
                }
            )

    checksum_field_candidates = [
        {
            "offset": offset,
            "note": "variable trailing/low bytes often used for checksums — unverified",
        }
        for offset in variable
        if offset >= 28
    ]

    return ApplicationBlockComparison(
        sources=sources,
        constant_offsets=constant,
        variable_offsets=variable,
        page_changes=page_changes,
        byte_changes=byte_changes,
        ndef_id_correlation=ndef_corr,
        counter_candidates=counter_candidates,
        timestamp_candidates=timestamp_candidates,
        checksum_field_candidates=checksum_field_candidates,
    )


def compare_application_block_files(paths: list[Path]) -> ApplicationBlockComparison:
    blocks: list[tuple[str, bytes]] = []
    for path in paths:
        block, _meta = load_application_block(path)
        blocks.append((str(path), block))
    return compare_application_blocks(blocks)
