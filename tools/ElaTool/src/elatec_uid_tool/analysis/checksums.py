from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ChecksumCandidate:
    algorithm: str
    coverage: str
    computed: int
    expected: int | None
    matches: bool
    note: str


def crc8(data: bytes, *, poly: int, init: int, xorout: int = 0) -> int:
    crc = init & 0xFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc ^ (xorout & 0xFF)


def crc16(
    data: bytes,
    *,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> int:
    crc = init & 0xFFFF

    def reflect(value: int, bits: int) -> int:
        result = 0
        for index in range(bits):
            if value & (1 << index):
                result |= 1 << (bits - 1 - index)
        return result

    for value in data:
        byte = reflect(value, 8) if refin else value
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    if refout:
        crc = reflect(crc, 16)
    return crc ^ (xorout & 0xFFFF)


def sum_mod(data: bytes, modulus: int) -> int:
    return sum(data) % modulus


def xor_fold(data: bytes) -> int:
    value = 0
    for item in data:
        value ^= item
    return value


def ones_complement_sum16(data: bytes) -> int:
    total = 0
    padded = data if len(data) % 2 == 0 else data + b"\x00"
    for index in range(0, len(padded), 2):
        total += (padded[index] << 8) | padded[index + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def twos_complement_sum8(data: bytes) -> int:
    return (-sum(data)) & 0xFF


def crc_a_iso(data: bytes) -> int:
    """ISO14443-A CRC_A as 16-bit integer (little-endian wire order)."""
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
    return crc


ALGORITHMS: list[tuple[str, Callable[[bytes], int], int]] = [
    ("crc8-atm", lambda data: crc8(data, poly=0x07, init=0x00), 8),
    ("crc8-maxim", lambda data: crc8(data, poly=0x31, init=0x00), 8),
    ("crc8-sae-j1850", lambda data: crc8(data, poly=0x1D, init=0xFF, xorout=0xFF), 8),
    (
        "crc16-ibm",
        lambda data: crc16(
            data, poly=0x8005, init=0x0000, refin=True, refout=True, xorout=0x0000
        ),
        16,
    ),
    (
        "crc16-ccitt-false",
        lambda data: crc16(
            data, poly=0x1021, init=0xFFFF, refin=False, refout=False, xorout=0x0000
        ),
        16,
    ),
    (
        "crc16-x25",
        lambda data: crc16(
            data, poly=0x1021, init=0xFFFF, refin=True, refout=True, xorout=0xFFFF
        ),
        16,
    ),
    ("crc-a", crc_a_iso, 16),
    ("sum8", lambda data: sum_mod(data, 256), 8),
    ("sum16", lambda data: sum_mod(data, 65536), 16),
    ("xor8", xor_fold, 8),
    ("ones-complement-16", ones_complement_sum16, 16),
    ("twos-complement-sum8", twos_complement_sum8, 8),
]


def _payload_slices(block: bytes) -> dict[str, bytes]:
    return {
        "all[0:32]": block,
        "payload[0:30]": block[:30],
        "payload[0:31]": block[:31],
        "pages_30_36[0:28]": block[:28],
        "pages_30_35[0:24]": block[:24],
        "without_page_37[0:28]": block[:28],
        "pages_30_33[0:16]": block[:16],
    }


def _storage_views(block: bytes) -> dict[str, tuple[int, int]]:
    """name -> (expected_value, width_bits)"""
    return {
        "u8@31": (block[31], 8),
        "u8@30": (block[30], 8),
        "u16le@30": (int.from_bytes(block[30:32], "little"), 16),
        "u16be@30": (int.from_bytes(block[30:32], "big"), 16),
        "u16le@28": (int.from_bytes(block[28:30], "little"), 16),
        "u16be@28": (int.from_bytes(block[28:30], "big"), 16),
    }


def evaluate_checksum_candidates(block: bytes) -> list[ChecksumCandidate]:
    """Evaluate a limited checksum set over common slices of a 32-byte block."""
    if len(block) != 32:
        raise ValueError("Application block musí mít přesně 32 bajtů.")

    results: list[ChecksumCandidate] = []
    for slice_name, payload in _payload_slices(block).items():
        # Skip slices that include the compared storage when storage overlaps.
        for algo_name, func, width in ALGORITHMS:
            computed = func(payload)
            for storage_name, (expected, store_width) in _storage_views(block).items():
                if width > store_width:
                    continue
                # Avoid trivial self-check when payload includes storage bytes.
                if slice_name.startswith("all") and storage_name.startswith("u"):
                    continue
                if "payload[0:31]" in slice_name and storage_name == "u8@31":
                    pass  # ok: storage excluded
                mask = (1 << store_width) - 1
                match_value = computed & mask
                expected_cmp = expected & mask
                matches = match_value == expected_cmp
                results.append(
                    ChecksumCandidate(
                        algorithm=algo_name,
                        coverage=f"{slice_name} vs {storage_name}",
                        computed=match_value,
                        expected=expected_cmp,
                        matches=matches,
                        note=(
                            "candidate match on single dump — not proof"
                            if matches
                            else "no match"
                        ),
                    )
                )
    return results


def evaluate_checksum_candidates_multi(blocks: list[bytes]) -> dict[str, Any]:
    """Score limited checksum candidates across multiple distinct blocks."""
    unique: list[bytes] = []
    seen: set[bytes] = set()
    for block in blocks:
        if len(block) != 32:
            raise ValueError("Každý application block musí mít 32 bajtů.")
        if block not in seen:
            seen.add(block)
            unique.append(block)

    total = len(unique)
    aggregate: dict[tuple[str, str, str], dict[str, Any]] = {}

    for block in unique:
        for candidate in evaluate_checksum_candidates(block):
            coverage, _, storage = candidate.coverage.partition(" vs ")
            key = (candidate.algorithm, coverage, storage)
            slot = aggregate.setdefault(
                key,
                {
                    "algorithm": candidate.algorithm,
                    "coverage": coverage,
                    "storage": storage,
                    "matching_samples": 0,
                    "total_samples": total,
                    "confidence": "low",
                    "note": "",
                },
            )
            if candidate.matches:
                slot["matching_samples"] += 1

    candidates: list[dict[str, Any]] = []
    for slot in aggregate.values():
        matched = slot["matching_samples"]
        if matched == 0:
            slot["confidence"] = "low"
            slot["note"] = "no matches"
        elif total == 1 and matched == 1:
            slot["confidence"] = "low"
            slot["note"] = "single-block match only — insufficient evidence"
        elif matched == total and total >= 3:
            slot["confidence"] = "high"
            slot["note"] = "matches all distinct blocks — candidate field"
        elif matched == total and total == 2:
            slot["confidence"] = "medium"
            slot["note"] = "matches both distinct blocks — repeatable correlation"
        elif matched >= max(2, (total + 1) // 2):
            slot["confidence"] = "medium"
            slot["note"] = "partial multi-block match — observed correlation"
        else:
            slot["confidence"] = "low"
            slot["note"] = "weak / sparse match — insufficient evidence"
        candidates.append(slot)

    candidates.sort(
        key=lambda item: (
            -item["matching_samples"],
            item["confidence"] != "high",
            item["algorithm"],
            item["coverage"],
        )
    )

    report_lines = [
        "Multi-sample checksum candidates",
        "================================",
        "",
        f"Distinct blocks: {total}",
        "Limited algorithm set (no unrestricted CRC brute-force).",
        "",
    ]
    interesting = [item for item in candidates if item["matching_samples"] > 0]
    if not interesting:
        report_lines.append("No matching candidates.")
    else:
        for item in interesting[:40]:
            report_lines.append(
                f"- {item['algorithm']} {item['coverage']} vs {item['storage']}: "
                f"{item['matching_samples']}/{item['total_samples']} "
                f"({item['confidence']}) — {item['note']}"
            )
    report_lines.append("")

    return {
        "total_distinct_blocks": total,
        "candidates": candidates,
        "report_text": "\n".join(report_lines) + "\n",
        "single_block_compat": [
            asdict(item) for item in (
                evaluate_checksum_candidates(unique[0]) if unique else []
            )
        ],
    }
