from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


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


def evaluate_checksum_candidates(block: bytes) -> list[ChecksumCandidate]:
    """Evaluate a limited checksum set over common slices of a 32-byte block."""
    if len(block) != 32:
        raise ValueError("Application block musí mít přesně 32 bajtů.")

    slices = {
        "all[0:32]": block,
        "payload[0:30]": block[:30],
        "payload[0:31]": block[:31],
        "pages_30_36[0:28]": block[:28],
        "pages_30_35[0:24]": block[:24],
        "without_page_37[0:28]": block[:28],
    }

    expected_tail = {
        "u8_last": block[-1],
        "u16_le_last": int.from_bytes(block[-2:], "little"),
        "u16_be_last": int.from_bytes(block[-2:], "big"),
    }

    algorithms: list[tuple[str, Callable[[bytes], int]]] = [
        ("crc8-atm", lambda data: crc8(data, poly=0x07, init=0x00)),
        ("crc8-maxim", lambda data: crc8(data, poly=0x31, init=0x00)),
        ("crc16-ibm", lambda data: crc16(
            data, poly=0x8005, init=0x0000, refin=True, refout=True, xorout=0x0000
        )),
        ("crc16-ccitt-false", lambda data: crc16(
            data, poly=0x1021, init=0xFFFF, refin=False, refout=False, xorout=0x0000
        )),
        ("crc16-x25", lambda data: crc16(
            data, poly=0x1021, init=0xFFFF, refin=True, refout=True, xorout=0xFFFF
        )),
        ("sum-mod-256", lambda data: sum_mod(data, 256)),
        ("sum-mod-65536", lambda data: sum_mod(data, 65536)),
        ("xor8", xor_fold),
        ("ones-complement-16", ones_complement_sum16),
    ]

    results: list[ChecksumCandidate] = []
    for slice_name, payload in slices.items():
        for algo_name, func in algorithms:
            computed = func(payload)
            for expect_name, expected in expected_tail.items():
                width_ok = (
                    (expect_name.startswith("u8") and computed <= 0xFF)
                    or (expect_name.startswith("u16") and computed <= 0xFFFF)
                )
                if not width_ok:
                    continue
                # Compare low bits for 8-bit algorithms stored in 16-bit field.
                match_value = computed & (0xFF if expect_name.startswith("u8") else 0xFFFF)
                expected_cmp = expected & (0xFF if expect_name.startswith("u8") else 0xFFFF)
                matches = match_value == expected_cmp
                results.append(
                    ChecksumCandidate(
                        algorithm=algo_name,
                        coverage=f"{slice_name} vs {expect_name}",
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
