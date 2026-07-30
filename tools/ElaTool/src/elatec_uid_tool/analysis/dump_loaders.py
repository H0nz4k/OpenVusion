from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_SIZE_BYTES,
    EEPROM_WATCH_START_PAGE,
)


def parse_page_number(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    # Support zero-padded decimal keys used by dump_vusion_ntag JSON ("048").
    if re.fullmatch(r"\d+", text):
        return int(text, 10)
    return int(text, 0)


def parse_hex_bytes(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        return bytes(int(item) & 0xFF for item in value)
    if isinstance(value, str):
        compact = re.sub(r"[^0-9A-Fa-f]", "", value.strip())
        if len(compact) % 2:
            raise ValueError(f"Hex řetězec má lichý počet znaků: {value!r}")
        return bytes.fromhex(compact)
    raise ValueError(f"Nepodporovaný formát bajtů: {type(value).__name__}")


def pages_to_block(
    pages: dict[int, bytes],
    *,
    start_page: int = EEPROM_WATCH_START_PAGE,
    end_page: int = EEPROM_WATCH_END_PAGE,
) -> bytes:
    expected = (end_page - start_page + 1) * 4
    chunks: list[bytes] = []
    for page in range(start_page, end_page + 1):
        if page not in pages:
            raise ValueError(f"V dumpu chybí stránka 0x{page:02X}.")
        data = pages[page]
        if len(data) != 4:
            raise ValueError(
                f"Stránka 0x{page:02X} musí mít 4 bajty, má {len(data)}."
            )
        chunks.append(data)
    block = b"".join(chunks)
    if len(block) != expected:
        raise ValueError(
            f"Application block musí mít {expected} bajtů, vyšlo {len(block)}."
        )
    return block


def extract_pages_from_json(document: dict[str, Any]) -> dict[int, bytes]:
    if "pages" in document:
        raw = document["pages"]
        if isinstance(raw, dict):
            return {
                parse_page_number(key): parse_hex_bytes(value)
                for key, value in raw.items()
            }
        if isinstance(raw, list):
            result: dict[int, bytes] = {}
            for item in raw:
                page = parse_page_number(item.get("page", item.get("page_number")))
                data = item.get("hex", item.get("data", item.get("bytes")))
                result[page] = parse_hex_bytes(data)
            return result
    for key in ("data_hex", "hex", "raw_hex"):
        if key in document:
            start = parse_page_number(document.get("start_page", 0))
            data = parse_hex_bytes(document[key])
            return {
                start + index: data[index * 4 : (index + 1) * 4]
                for index in range(len(data) // 4)
            }
    raise ValueError("JSON neobsahuje rozpoznatelná page data.")


def load_application_block(
    path: Path,
    *,
    start_page: int = EEPROM_WATCH_START_PAGE,
) -> tuple[bytes, dict[str, Any]]:
    """Load 32-byte application block from JSON or BIN dump."""
    path = Path(path)
    meta: dict[str, Any] = {"source": str(path), "format": path.suffix.lower()}

    if path.suffix.lower() == ".bin":
        data = path.read_bytes()
        if len(data) == EEPROM_WATCH_SIZE_BYTES:
            return data, meta
        # Full EEPROM dump: extract window by absolute byte offset.
        offset = start_page * 4
        end = offset + EEPROM_WATCH_SIZE_BYTES
        if len(data) < end:
            raise ValueError(
                f"BIN je příliš krátký ({len(data)} B) pro stránky "
                f"0x{start_page:02X}+."
            )
        return data[offset:end], meta

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Kořen JSON musí být objekt.")
    meta["uid"] = document.get("uid")
    meta["get_version"] = document.get("get_version")

    # Direct block field.
    if "application_block" in document:
        block = parse_hex_bytes(document["application_block"])
        if len(block) != EEPROM_WATCH_SIZE_BYTES:
            raise ValueError("application_block musí mít 32 bajtů.")
        return block, meta

    pages = extract_pages_from_json(document)
    # Prefer explicit window; if dump uses decimal keys, 0x30 == 48.
    try:
        return pages_to_block(pages), meta
    except ValueError:
        # Some dumps may only contain the 32-byte slice starting at start_page.
        if len(pages) == 8 and min(pages) == start_page:
            return pages_to_block(pages, start_page=start_page), meta
        raise
