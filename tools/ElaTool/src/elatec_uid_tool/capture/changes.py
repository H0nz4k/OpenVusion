from __future__ import annotations

from dataclasses import dataclass

from ..ntag import SESSION_REGISTER_NAMES


@dataclass(frozen=True)
class ByteChange:
    offset: int
    old: int
    new: int


@dataclass(frozen=True)
class RangeChange:
    start: int
    end: int  # inclusive


def changed_bits(old: int, new: int) -> list[int]:
    """Vrátí indexy bitů (0–7), které se mezi dvěma bajty změnily."""
    mask = (old ^ new) & 0xFF
    return [bit for bit in range(8) if mask & (1 << bit)]


def byte_changes(previous: bytes, current: bytes) -> list[ByteChange]:
    if len(previous) != len(current):
        raise ValueError(
            f"Délky se liší: previous={len(previous)}, current={len(current)}"
        )
    return [
        ByteChange(offset=index, old=old, new=new)
        for index, (old, new) in enumerate(zip(previous, current))
        if old != new
    ]


def changed_ranges(changes: list[ByteChange]) -> list[RangeChange]:
    """Spojí sousední změněné offsety do souvislých rozsahů."""
    if not changes:
        return []

    ordered = sorted(changes, key=lambda item: item.offset)
    ranges: list[RangeChange] = []
    start = ordered[0].offset
    end = ordered[0].offset

    for item in ordered[1:]:
        if item.offset == end + 1:
            end = item.offset
            continue
        ranges.append(RangeChange(start=start, end=end))
        start = end = item.offset

    ranges.append(RangeChange(start=start, end=end))
    return ranges


def session_changes(previous: bytes, current: bytes) -> dict:
    """Porovná 8bajtové session registry; nepřiřazuje bitům význam."""
    if len(previous) != 8 or len(current) != 8:
        raise ValueError("Session registry musí mít přesně 8 bajtů.")

    changed_registers: list[dict] = []
    for index, (old, new) in enumerate(zip(previous, current)):
        if old == new:
            continue
        page = 0xEC if index < 4 else 0xED
        offset = index if index < 4 else index - 4
        changed_registers.append(
            {
                "name": SESSION_REGISTER_NAMES[index],
                "page": page,
                "offset": offset,
                "old": old,
                "new": new,
                "old_hex": f"0x{old:02X}",
                "new_hex": f"0x{new:02X}",
                "changed_bits": changed_bits(old, new),
            }
        )

    return {
        "changed": bool(changed_registers),
        "registers": changed_registers,
    }


def sram_changes(previous: bytes, current: bytes) -> dict:
    """Porovná 64bajtovou SRAM; nula ≠ chybějící odpověď."""
    if len(previous) != 64 or len(current) != 64:
        raise ValueError("SRAM musí mít přesně 64 bajtů.")

    changes = byte_changes(previous, current)
    ranges = changed_ranges(changes)
    return {
        "changed": bool(changes),
        "offsets": [item.offset for item in changes],
        "bytes": [
            {
                "offset": item.offset,
                "old": item.old,
                "new": item.new,
                "old_hex": f"0x{item.old:02X}",
                "new_hex": f"0x{item.new:02X}",
            }
            for item in changes
        ],
        "ranges": [
            {"start": item.start, "end": item.end} for item in ranges
        ],
        "previous_hex": previous.hex(" ").upper(),
        "current_hex": current.hex(" ").upper(),
    }


def eeprom_changes(
    previous: bytes,
    current: bytes,
    *,
    start_page: int = 0x30,
) -> dict:
    """Porovná sledovaný EEPROM blok po bajtech i po stránkách."""
    if len(previous) != len(current):
        raise ValueError("EEPROM rozsahy musí mít stejnou délku.")
    if len(previous) % 4:
        raise ValueError("EEPROM rozsah musí být násobek 4 bajtů.")

    changes = byte_changes(previous, current)
    page_diffs: list[dict] = []
    page_count = len(previous) // 4

    for page_index in range(page_count):
        offset = page_index * 4
        old_page = previous[offset : offset + 4]
        new_page = current[offset : offset + 4]
        if old_page == new_page:
            continue
        page_diffs.append(
            {
                "page": start_page + page_index,
                "old_hex": old_page.hex(" ").upper(),
                "new_hex": new_page.hex(" ").upper(),
                "byte_offsets": [
                    item.offset
                    for item in changes
                    if offset <= item.offset < offset + 4
                ],
            }
        )

    return {
        "changed": bool(changes),
        "start_page": start_page,
        "pages": page_diffs,
        "bytes": [
            {
                "absolute_offset": item.offset,
                "page": start_page + (item.offset // 4),
                "offset_in_page": item.offset % 4,
                "old": item.old,
                "new": item.new,
                "old_hex": f"0x{item.old:02X}",
                "new_hex": f"0x{item.new:02X}",
            }
            for item in changes
        ],
    }
