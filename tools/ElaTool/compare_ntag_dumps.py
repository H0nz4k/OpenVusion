#!/usr/bin/env python3
"""
compare_ntag_dumps.py

Porovná dva JSON dumpy NTAG po stránkách a bajtech.

Podporované běžné tvary vstupu:
1) {"pages": {"0x00": "04 36 7F 5A", "0x01": "2D 72 80 00", ...}}
2) {"pages": [{"page": "0x00", "hex": "04 36 7F 5A"}, ...]}
3) {"dump": {"0x00": [4, 54, 127, 90], ...}}
4) {"data_hex": "04 36 7F 5A ...", "start_page": 0}
5) {"data": [4, 54, 127, 90, ...], "start_page": 0}

Výstup:
- shodné / rozdílné stránky,
- přesné offsety bajtů,
- původní a nové hodnoty,
- volitelný JSON report.

Použití:
    python compare_ntag_dumps.py dump_A.json dump_B.json
    python compare_ntag_dumps.py dump_A.json dump_B.json --json-report rozdily.json
    python compare_ntag_dumps.py dump_A.json dump_B.json --only-differences

Návratové kódy:
    0 = dumpy jsou shodné
    1 = dumpy se liší
    2 = chyba vstupu nebo formátu
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


PAGE_SIZE = 4


@dataclass
class ByteDifference:
    page: int
    offset: int
    absolute_offset: int
    value_a: int | None
    value_b: int | None


@dataclass
class PageDifference:
    page: int
    bytes_a: list[int] | None
    bytes_b: list[int] | None
    byte_differences: list[ByteDifference]


def parse_page_number(value: Any) -> int:
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("Prázdné číslo stránky.")

    if text.lower().startswith("0x"):
        return int(text, 16)

    return int(text, 10)


def parse_hex_bytes(value: Any) -> list[int]:
    if value is None:
        return []

    if isinstance(value, (bytes, bytearray)):
        return list(value)

    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            if isinstance(item, int):
                number = item
            else:
                text = str(item).strip()
                number = int(text, 16) if text.lower().startswith("0x") else int(text)
            if not 0 <= number <= 0xFF:
                raise ValueError(f"Hodnota bajtu je mimo rozsah 0–255: {item!r}")
            result.append(number)
        return result

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []

        # Podpora "04 36 7F 5A", "04367F5A", "04:36:7F:5A", "04-36-7F-5A"
        compact = re.sub(r"[^0-9A-Fa-f]", "", text)
        if len(compact) % 2 != 0:
            raise ValueError(f"Hex řetězec má lichý počet znaků: {value!r}")
        return [int(compact[i:i + 2], 16) for i in range(0, len(compact), 2)]

    raise ValueError(f"Nepodporovaný formát bajtů: {type(value).__name__}")


def split_into_pages(data: Iterable[int], start_page: int = 0) -> dict[int, list[int]]:
    raw = list(data)
    if len(raw) % PAGE_SIZE != 0:
        raise ValueError(
            f"Délka dat {len(raw)} není násobkem velikosti stránky {PAGE_SIZE} bajty."
        )

    return {
        start_page + index // PAGE_SIZE: raw[index:index + PAGE_SIZE]
        for index in range(0, len(raw), PAGE_SIZE)
    }


def normalize_pages_object(value: Any) -> dict[int, list[int]]:
    pages: dict[int, list[int]] = {}

    if isinstance(value, dict):
        for key, page_data in value.items():
            page = parse_page_number(key)

            if isinstance(page_data, dict):
                for candidate in ("hex", "data", "bytes", "value"):
                    if candidate in page_data:
                        page_data = page_data[candidate]
                        break

            pages[page] = parse_hex_bytes(page_data)
        return pages

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Položka seznamu pages není objekt.")

            page_key = next(
                (key for key in ("page", "page_number", "address", "index") if key in item),
                None,
            )
            data_key = next(
                (key for key in ("hex", "data", "bytes", "value") if key in item),
                None,
            )

            if page_key is None or data_key is None:
                raise ValueError(
                    "Položka pages musí obsahovat číslo stránky a data."
                )

            pages[parse_page_number(item[page_key])] = parse_hex_bytes(item[data_key])

        return pages

    raise ValueError("Pole pages/dump nemá podporovaný formát.")


def extract_pages(document: Any) -> dict[int, list[int]]:
    if not isinstance(document, dict):
        raise ValueError("Kořen JSON souboru musí být objekt.")

    # Nejběžnější struktury.
    for key in ("pages", "dump", "memory", "eeprom"):
        if key in document:
            try:
                pages = normalize_pages_object(document[key])
                if pages:
                    return pages
            except ValueError:
                pass

    # Souvislá data jako hex nebo seznam bajtů.
    for key in ("data_hex", "hex", "raw_hex"):
        if key in document:
            start_page = parse_page_number(document.get("start_page", 0))
            return split_into_pages(parse_hex_bytes(document[key]), start_page)

    for key in ("data", "raw", "bytes"):
        if key in document and isinstance(document[key], (list, str, bytes, bytearray)):
            start_page = parse_page_number(document.get("start_page", 0))
            return split_into_pages(parse_hex_bytes(document[key]), start_page)

    # Poslední pokus: kořenový objekt je přímo mapa stránek.
    try:
        pages = normalize_pages_object(document)
        if pages:
            return pages
    except ValueError:
        pass

    raise ValueError(
        "Nepodařilo se najít data dumpu. Očekávám například klíč "
        "'pages', 'dump', 'data_hex' nebo 'data'."
    )


def load_dump(path: Path) -> dict[int, list[int]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Soubor neexistuje: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Neplatný JSON v souboru {path}: řádek {exc.lineno}, sloupec {exc.colno}"
        ) from exc

    pages = extract_pages(document)

    for page, page_data in pages.items():
        if len(page_data) != PAGE_SIZE:
            raise ValueError(
                f"Stránka 0x{page:02X} v souboru {path} má {len(page_data)} bajtů; "
                f"očekávány jsou {PAGE_SIZE}."
            )

    return pages


def compare_pages(
    pages_a: dict[int, list[int]],
    pages_b: dict[int, list[int]],
) -> list[PageDifference]:
    differences: list[PageDifference] = []

    for page in sorted(set(pages_a) | set(pages_b)):
        data_a = pages_a.get(page)
        data_b = pages_b.get(page)

        if data_a == data_b:
            continue

        byte_differences: list[ByteDifference] = []

        for offset in range(PAGE_SIZE):
            value_a = data_a[offset] if data_a is not None else None
            value_b = data_b[offset] if data_b is not None else None

            if value_a != value_b:
                byte_differences.append(
                    ByteDifference(
                        page=page,
                        offset=offset,
                        absolute_offset=page * PAGE_SIZE + offset,
                        value_a=value_a,
                        value_b=value_b,
                    )
                )

        differences.append(
            PageDifference(
                page=page,
                bytes_a=data_a,
                bytes_b=data_b,
                byte_differences=byte_differences,
            )
        )

    return differences


def format_page(data: list[int] | None) -> str:
    if data is None:
        return "<chybí>"
    return " ".join(f"{byte:02X}" for byte in data)


def format_byte(value: int | None) -> str:
    return "--" if value is None else f"{value:02X}"


def print_report(
    path_a: Path,
    path_b: Path,
    pages_a: dict[int, list[int]],
    pages_b: dict[int, list[int]],
    differences: list[PageDifference],
    only_differences: bool,
) -> None:
    common_pages = set(pages_a) & set(pages_b)
    identical_pages = sum(1 for page in common_pages if pages_a[page] == pages_b[page])
    only_a = sorted(set(pages_a) - set(pages_b))
    only_b = sorted(set(pages_b) - set(pages_a))
    changed_pages = [
        diff for diff in differences
        if diff.bytes_a is not None and diff.bytes_b is not None
    ]
    changed_bytes = sum(len(diff.byte_differences) for diff in differences)

    print("NTAG dump comparison")
    print("====================")
    print(f"A: {path_a}")
    print(f"B: {path_b}")
    print()
    print(f"Pages in A:          {len(pages_a)}")
    print(f"Pages in B:          {len(pages_b)}")
    print(f"Identical pages:     {identical_pages}")
    print(f"Changed pages:       {len(changed_pages)}")
    print(f"Pages only in A:     {len(only_a)}")
    print(f"Pages only in B:     {len(only_b)}")
    print(f"Changed byte values: {changed_bytes}")
    print()

    if not differences:
        print("RESULT: DUMPY JSOU SHODNÉ")
        return

    print("RESULT: DUMPY SE LIŠÍ")
    print()

    if only_a:
        print("Pages only in A:")
        print("  " + ", ".join(f"0x{page:02X}" for page in only_a))
        print()

    if only_b:
        print("Pages only in B:")
        print("  " + ", ".join(f"0x{page:02X}" for page in only_b))
        print()

    print("Differences")
    print("-----------")

    for diff in differences:
        print(f"Page 0x{diff.page:02X}")
        print(f"  A: {format_page(diff.bytes_a)}")
        print(f"  B: {format_page(diff.bytes_b)}")

        for byte_diff in diff.byte_differences:
            print(
                f"  byte +{byte_diff.offset} "
                f"(absolute 0x{byte_diff.absolute_offset:04X}): "
                f"{format_byte(byte_diff.value_a)} -> {format_byte(byte_diff.value_b)}"
            )
        print()

    if not only_differences:
        print("Unchanged ranges")
        print("----------------")
        unchanged = sorted(
            page for page in common_pages if pages_a[page] == pages_b[page]
        )

        if not unchanged:
            print("None")
            return

        ranges: list[tuple[int, int]] = []
        start = previous = unchanged[0]

        for page in unchanged[1:]:
            if page == previous + 1:
                previous = page
                continue
            ranges.append((start, previous))
            start = previous = page

        ranges.append((start, previous))

        for start, end in ranges:
            if start == end:
                print(f"0x{start:02X}")
            else:
                print(f"0x{start:02X}-0x{end:02X}")


def write_json_report(
    output_path: Path,
    path_a: Path,
    path_b: Path,
    pages_a: dict[int, list[int]],
    pages_b: dict[int, list[int]],
    differences: list[PageDifference],
) -> None:
    report = {
        "schema": 1,
        "file_a": str(path_a),
        "file_b": str(path_b),
        "identical": not differences,
        "page_count_a": len(pages_a),
        "page_count_b": len(pages_b),
        "difference_count_pages": len(differences),
        "difference_count_bytes": sum(
            len(diff.byte_differences) for diff in differences
        ),
        "differences": [
            {
                "page": f"0x{diff.page:02X}",
                "page_number": diff.page,
                "hex_a": format_page(diff.bytes_a),
                "hex_b": format_page(diff.bytes_b),
                "byte_differences": [
                    {
                        **asdict(byte_diff),
                        "page": f"0x{byte_diff.page:02X}",
                        "value_a_hex": format_byte(byte_diff.value_a),
                        "value_b_hex": format_byte(byte_diff.value_b),
                    }
                    for byte_diff in diff.byte_differences
                ],
            }
            for diff in differences
        ],
    }

    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Porovná dva JSON dumpy NTAG po stránkách a bajtech."
    )
    parser.add_argument("dump_a", type=Path, help="První JSON dump")
    parser.add_argument("dump_b", type=Path, help="Druhý JSON dump")
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Volitelně uloží strojově čitelný JSON report.",
    )
    parser.add_argument(
        "--only-differences",
        action="store_true",
        help="Nevypisuje rozsahy shodných stránek.",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        pages_a = load_dump(args.dump_a)
        pages_b = load_dump(args.dump_b)
        differences = compare_pages(pages_a, pages_b)

        print_report(
            args.dump_a,
            args.dump_b,
            pages_a,
            pages_b,
            differences,
            args.only_differences,
        )

        if args.json_report:
            write_json_report(
                args.json_report,
                args.dump_a,
                args.dump_b,
                pages_a,
                pages_b,
                differences,
            )
            print()
            print(f"JSON report uložen: {args.json_report}")

        return 1 if differences else 0

    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
