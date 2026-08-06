"""Read-only FeliCa / NFC Forum Type 3 helpers for the shared capture engine.

This module intentionally exposes only conservative read operations used by
HWSniff/PCSniff technology auto-dispatch. No FeliCa write command or write
service is implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import SerialCommunicationError

FELICA_NDEF_SYSTEM_CODE = 0x12FC
FELICA_NDEF_RO_SERVICE = 0x000B


@dataclass(frozen=True)
class FelicaPollResult:
    system_code: int
    idm: bytes
    pmm: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_code": f"0x{self.system_code:04X}",
            "idm": self.idm.hex().upper(),
            "pmm": self.pmm.hex().upper(),
        }


@dataclass(frozen=True)
class FelicaReadResult:
    block_number: int
    service_code: int
    idm: bytes
    data: bytes
    raw_response: bytes
    status_flag1: int
    status_flag2: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "block": self.block_number,
            "service_code": f"0x{self.service_code:04X}",
            "idm": self.idm.hex().upper(),
            "data_hex": self.data.hex().upper(),
            "raw_response_hex": self.raw_response.hex().upper(),
            "status_flag1": f"0x{self.status_flag1:02X}",
            "status_flag2": f"0x{self.status_flag2:02X}",
        }


def _request(client: Any, command: bytes) -> bytes:
    request = getattr(client, "_request", None)
    if request is None:
        raise AttributeError("Simple Protocol client has no _request method")
    return request(command)


def felica_poll(client: Any, system_code: int) -> FelicaPollResult:
    """ELATEC Simple Protocol FeliCa Poll (1D04), read-only."""
    payload = _request(client, b"\x1D\x04" + system_code.to_bytes(2, "little"))
    if not payload:
        raise SerialCommunicationError("FeliCa_Poll returned empty payload")
    result = payload[0]
    if result == 0:
        raise SerialCommunicationError(
            f"FeliCa_Poll(0x{system_code:04X}) returned Result=false"
        )
    if result != 1:
        raise SerialCommunicationError(
            f"FeliCa_Poll returned invalid Bool: {result}"
        )
    if len(payload) < 17:
        raise SerialCommunicationError(
            f"FeliCa_Poll returned short payload: {payload.hex().upper()}"
        )
    return FelicaPollResult(
        system_code=system_code,
        idm=payload[1:9],
        pmm=payload[9:17],
    )


def request_system_codes(client: Any) -> list[int]:
    """ELATEC Simple Protocol FeliCa RequestSystemCode (1D03)."""
    payload = _request(client, b"\x1D\x03\x08")
    if not payload:
        raise SerialCommunicationError("FeliCa_RequestSystemCode returned empty payload")
    result = payload[0]
    if result == 0:
        return []
    if result != 1:
        raise SerialCommunicationError(
            f"FeliCa_RequestSystemCode returned invalid Bool: {result}"
        )
    if len(payload) < 2:
        raise SerialCommunicationError("FeliCa_RequestSystemCode missing count")
    count = payload[1]
    expected = 2 + count * 2
    if len(payload) < expected:
        raise SerialCommunicationError(
            "FeliCa_RequestSystemCode returned truncated system-code array"
        )
    return [
        int.from_bytes(payload[2 + i * 2 : 4 + i * 2], "little")
        for i in range(count)
    ]


def request_service_diag(client: Any, service_code: int) -> bool:
    """Diagnostic RequestService. Result=false is a valid observation.

    This result MUST NOT gate a later Read Without Encryption. The physical
    SOLUM target returned false here while direct CHECK on service 0x000B
    succeeded.
    """
    payload = _request(
        client,
        b"\x1D\x05\x01" + service_code.to_bytes(2, "little"),
    )
    if not payload:
        raise SerialCommunicationError("FeliCa_RequestService returned empty payload")
    result = payload[0]
    if result == 0:
        return False
    if result != 1:
        raise SerialCommunicationError(
            f"FeliCa_RequestService returned invalid Bool: {result}"
        )
    return True


def build_check_frame(
    idm: bytes,
    block_number: int,
    *,
    service_code: int = FELICA_NDEF_RO_SERVICE,
) -> bytes:
    """Build one-block FeliCa Read Without Encryption / CHECK frame."""
    if len(idm) != 8:
        raise ValueError("FeliCa IDm must be exactly 8 bytes")
    if not 0 <= block_number <= 0xFF:
        raise ValueError("block_number must be 0..255")
    body = (
        b"\x06"
        + idm
        + b"\x01"
        + service_code.to_bytes(2, "little")
        + b"\x01"
        + bytes((0x80, block_number))
    )
    return bytes((1 + len(body),)) + body


def _felica_tdx(client: Any, frame: bytes) -> bytes | None:
    """ELATEC FeliCa_TDX wrapper used only with our read-only CHECK frame."""
    if not frame or len(frame) > 0xFF:
        raise ValueError("FeliCa frame must contain 1..255 bytes")
    command = b"\x1D\x00" + bytes((len(frame),)) + frame + b"\xFF\xFF\x01"
    payload = _request(client, command)
    if not payload:
        raise SerialCommunicationError("FeliCa_TDX returned empty payload")
    result = payload[0]
    if result == 0:
        return None
    if result != 1:
        raise SerialCommunicationError(f"FeliCa_TDX returned invalid Bool: {result}")

    rest = payload[1:]
    if not rest:
        raise SerialCommunicationError("FeliCa_TDX success without RX bytes")
    # Physically verified TWN4 form: RXByteCnt + FeliCa frame.
    if rest[0] == len(rest) - 1:
        return rest[1:]
    # Fail-soft compatibility for a 16-bit count wrapper.
    if len(rest) >= 2 and int.from_bytes(rest[:2], "little") == len(rest) - 2:
        return rest[2:]
    # Some firmware builds may return the FeliCa frame directly.
    if rest[0] == len(rest):
        return rest
    raise SerialCommunicationError(
        f"Unknown FeliCa_TDX response wrapper: {payload.hex().upper()}"
    )


def read_without_encryption_block(
    client: Any,
    idm: bytes,
    block_number: int,
    *,
    service_code: int = FELICA_NDEF_RO_SERVICE,
) -> FelicaReadResult:
    """Read exactly one FeliCa block from a read-only service."""
    frame = build_check_frame(idm, block_number, service_code=service_code)
    rx = _felica_tdx(client, frame)
    if rx is None:
        raise SerialCommunicationError(
            f"FeliCa CHECK block {block_number} returned Result=false"
        )

    original = rx
    # Compatibility if a wrapper removed the FeliCa LEN byte.
    if rx and rx[0] == 0x07:
        rx = bytes((len(rx) + 1,)) + rx
    if len(rx) < 13:
        raise SerialCommunicationError(
            f"FeliCa CHECK response too short: {original.hex().upper()}"
        )
    if rx[1] != 0x07:
        raise SerialCommunicationError(
            f"Unexpected FeliCa response code 0x{rx[1]:02X}"
        )

    response_idm = rx[2:10]
    sf1 = rx[10]
    sf2 = rx[11]
    block_count = rx[12]
    data = rx[13:]

    if response_idm != idm:
        raise SerialCommunicationError(
            "FeliCa CHECK IDm changed during capture: "
            f"{idm.hex().upper()} -> {response_idm.hex().upper()}"
        )
    if sf1 != 0 or sf2 != 0:
        raise SerialCommunicationError(
            f"FeliCa CHECK status error SF1=0x{sf1:02X} SF2=0x{sf2:02X}"
        )
    if block_count != 1 or len(data) != 16:
        raise SerialCommunicationError(
            f"Unexpected FeliCa block shape count={block_count} len={len(data)}"
        )

    return FelicaReadResult(
        block_number=block_number,
        service_code=service_code,
        idm=response_idm,
        data=data,
        raw_response=original,
        status_flag1=sf1,
        status_flag2=sf2,
    )


def select_ndef_and_read_block(
    client: Any,
    expected_idm: bytes,
    block_number: int,
) -> FelicaReadResult:
    """Re-Poll 0x12FC, verify target IDm, then read one public NDEF block."""
    selected = felica_poll(client, FELICA_NDEF_SYSTEM_CODE)
    if selected.idm != expected_idm:
        raise SerialCommunicationError(
            "FeliCa Poll(0x12FC) selected another target: "
            f"{expected_idm.hex().upper()} -> {selected.idm.hex().upper()}"
        )
    return read_without_encryption_block(
        client,
        expected_idm,
        block_number,
        service_code=FELICA_NDEF_RO_SERVICE,
    )


def parse_type3_attribute_block(data: bytes) -> dict[str, Any]:
    """Parse the 16-byte NFC Forum Type 3 Attribute Information Block."""
    if len(data) != 16:
        raise ValueError("Type 3 Attribute Information Block must be 16 bytes")
    checksum_expected = int.from_bytes(data[14:16], "big")
    checksum_actual = sum(data[:14]) & 0xFFFF
    version = data[0]
    return {
        "raw_hex": data.hex().upper(),
        "valid_checksum": checksum_actual == checksum_expected,
        "version_raw": f"0x{version:02X}",
        "version_major": version >> 4,
        "version_minor": version & 0x0F,
        "nbr": data[1],
        "nbw": data[2],
        "nmaxb": int.from_bytes(data[3:5], "big"),
        "writef": f"0x{data[9]:02X}",
        "rwflag": f"0x{data[10]:02X}",
        "ndef_length": int.from_bytes(data[11:14], "big"),
        "checksum_expected": f"0x{checksum_expected:04X}",
        "checksum_actual": f"0x{checksum_actual:04X}",
    }
