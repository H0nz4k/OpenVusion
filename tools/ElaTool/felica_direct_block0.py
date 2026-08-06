#!/usr/bin/env python3
"""
felica_direct_block0.py

STRICTNĚ READ-ONLY experiment pro SOLUM / FeliCa Type 3 přes ELATEC TWN4
Simple Protocol.

Cíl:
- SearchTag + stabilita ID
- FeliCa Poll(FFFF)
- RequestSystemCode
- FeliCa Poll(12FC)
- RequestService(000B) pouze diagnosticky
- bez ohledu na RequestService výsledek provést JEDEN přímý
  Read Without Encryption / CHECK pro service 000B, block 0000
  přes FeliCa_TDX
- žádný WRITE příkaz není implementován

Spuštění z tools/ElaTool:
    ./.venv/Scripts/python.exe felica_direct_block0.py --port COM13

Poznámka:
Skript záměrně používá existující elatec_uid_tool.protocol.SimpleProtocolClient
a neimplementuje druhý serial transport.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from elatec_uid_tool.protocol import (
    SimpleProtocolClient,
    SerialCommunicationError,
    ProtocolError,
)

EXPECTED_TAG_TYPE = 0x85
NDEF_SYSTEM_CODE = 0x12FC
NDEF_RO_SERVICE = 0x000B


def hx(data: bytes) -> str:
    return data.hex().upper()


def poll(client: SimpleProtocolClient, system_code: int) -> tuple[bytes, bytes]:
    cmd = b"\x1D\x04" + system_code.to_bytes(2, "little")
    print(f"TX FeliCa_Poll(0x{system_code:04X}): {hx(cmd)}")
    payload = client._request(cmd)
    if not payload:
        raise RuntimeError("FeliCa_Poll: prázdná odpověď.")
    if payload[0] == 0:
        raise RuntimeError(f"FeliCa_Poll(0x{system_code:04X}): Result=false.")
    if payload[0] != 1:
        raise RuntimeError(f"FeliCa_Poll: neplatný Result 0x{payload[0]:02X}, payload={hx(payload)}")
    if len(payload) < 17:
        raise RuntimeError(f"FeliCa_Poll: krátká odpověď ({len(payload)} B): {hx(payload)}")
    idm = payload[1:9]
    pmm = payload[9:17]
    print(f"  IDm={hx(idm)}")
    print(f"  PMm={hx(pmm)}")
    return idm, pmm


def request_system_codes(client: SimpleProtocolClient) -> list[int]:
    cmd = b"\x1D\x03\x08"
    print(f"TX FeliCa_RequestSystemCode: {hx(cmd)}")
    payload = client._request(cmd)
    if not payload:
        raise RuntimeError("RequestSystemCode: prázdná odpověď.")
    if payload[0] == 0:
        print("  Result=false")
        return []
    if payload[0] != 1 or len(payload) < 2:
        raise RuntimeError(f"RequestSystemCode: neplatná odpověď: {hx(payload)}")
    count = payload[1]
    expected = 2 + count * 2
    if len(payload) < expected:
        raise RuntimeError(f"RequestSystemCode: očekáváno min. {expected} B, přišlo {len(payload)}: {hx(payload)}")
    codes = [int.from_bytes(payload[2 + i * 2 : 4 + i * 2], "little") for i in range(count)]
    print("  SystemCodes=" + ", ".join(f"0x{x:04X}" for x in codes))
    return codes


def request_service_diag(client: SimpleProtocolClient, service_code: int) -> bool:
    cmd = b"\x1D\x05\x01" + service_code.to_bytes(2, "little")
    print(f"TX FeliCa_RequestService(0x{service_code:04X}): {hx(cmd)}")
    payload = client._request(cmd)
    if not payload:
        raise RuntimeError("RequestService: prázdná odpověď.")
    if payload[0] == 0:
        print("  Result=false (pokračuji jedním read-only CHECK pokusem)")
        return False
    if payload[0] != 1:
        raise RuntimeError(f"RequestService: neplatný Result: {hx(payload)}")
    print(f"  Result=true payload={hx(payload)}")
    return True


def build_felica_check_frame(idm: bytes, service_code: int = NDEF_RO_SERVICE, block_number: int = 0) -> bytes:
    if len(idm) != 8:
        raise ValueError("IDm musí mít 8 bajtů.")
    if not 0 <= block_number <= 0xFF:
        raise ValueError("Block number musí být 0..255.")
    body = (
        b"\x06"
        + idm
        + b"\x01"
        + service_code.to_bytes(2, "little")
        + b"\x01"
        + bytes([0x80, block_number])
    )
    return bytes([1 + len(body)]) + body


def felica_tdx(client: SimpleProtocolClient, frame: bytes, number_of_blocks: int = 1) -> Optional[bytes]:
    if not frame or len(frame) > 0xFF:
        raise ValueError("FeliCa frame musí mít 1..255 B.")
    cmd = b"\x1D\x00" + bytes([len(frame)]) + frame + b"\xFF\xFF" + bytes([number_of_blocks])
    print(f"TX FeliCa_TDX/CHECK: {hx(cmd)}")
    payload = client._request(cmd)
    print(f"RX SimpleProtocol payload: {hx(payload)}")
    if not payload:
        raise RuntimeError("FeliCa_TDX: prázdná odpověď.")
    if payload[0] == 0:
        return None
    if payload[0] != 1:
        raise RuntimeError(f"FeliCa_TDX: neplatný Result: {hx(payload)}")
    rest = payload[1:]
    if not rest:
        raise RuntimeError("FeliCa_TDX: Result=true, ale chybí RX data.")
    if rest[0] == len(rest) - 1:
        return rest[1:]
    if len(rest) >= 2:
        n16 = int.from_bytes(rest[:2], "little")
        if n16 == len(rest) - 2:
            return rest[2:]
    if rest[0] == len(rest):
        return rest
    print("VAROVÁNÍ: Neznámé kódování FeliCa_TDX success payloadu; vracím zbytek pro ruční analýzu.")
    return rest


def parse_type3_attribute_block(data: bytes) -> dict:
    if len(data) != 16:
        return {"valid": False, "reason": "not_16_bytes"}
    checksum_expected = int.from_bytes(data[14:16], "big")
    checksum_actual = sum(data[0:14]) & 0xFFFF
    version = data[0]
    return {
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


def parse_check_response(rx: bytes, expected_idm: bytes) -> dict:
    original = rx
    if rx and rx[0] == 0x07:
        rx = bytes([len(rx) + 1]) + rx
    if len(rx) < 13:
        raise RuntimeError(f"CHECK response je příliš krátká: {hx(original)}")
    response_code = rx[1]
    idm = rx[2:10]
    sf1, sf2, blocks = rx[10], rx[11], rx[12]
    data = rx[13:]
    result = {
        "raw_hex": hx(original),
        "response_code": f"0x{response_code:02X}",
        "idm": hx(idm),
        "idm_match": idm == expected_idm,
        "status_flag1": f"0x{sf1:02X}",
        "status_flag2": f"0x{sf2:02X}",
        "number_of_blocks": blocks,
        "data_hex": hx(data),
    }
    if response_code != 0x07:
        result["error"] = "unexpected_response_code"
        return result
    if idm != expected_idm:
        result["error"] = "idm_mismatch"
        return result
    if sf1 != 0 or sf2 != 0:
        result["error"] = "felica_status_error"
        return result
    if blocks != 1 or len(data) != 16:
        result["error"] = "unexpected_block_shape"
        return result
    result["status"] = "SUCCESS"
    result["block0"] = hx(data)
    result["attribute_block"] = parse_type3_attribute_block(data)
    return result


def confirm_tag(client: SimpleProtocolClient, first_id: bytes, count: int = 3) -> None:
    for i in range(1, count + 1):
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError(f"UID confirm {i}/{count}: tag zmizel.")
        print(f"UID confirm {i}/{count}: type=0x{tag.tag_type:02X} id={tag.id_hex} bits={tag.id_bit_count}")
        if tag.id_bytes != first_id:
            raise RuntimeError(f"UID mismatch: očekáváno {hx(first_id)}, přišlo {tag.id_hex}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only SOLUM/FeliCa Type 3 direct block-0 test.")
    ap.add_argument("--port", required=True, help="COM port, např. COM13")
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--json", dest="json_path", default="felica_direct_block0_result.json")
    args = ap.parse_args()

    result: dict = {"port": args.port, "strict_read_only": True, "service_code": "0x000B", "block": 0}
    print("=" * 72)
    print(" SOLUM / FeliCa Type 3 — DIRECT BLOCK 0 TEST (STRICT READ-ONLY)")
    print("=" * 72)
    print("Žádný WRITE příkaz není v tomto skriptu implementován.\n")

    try:
        with SimpleProtocolClient(args.port, timeout=args.timeout) as client:
            info = client.read_info()
            print(f"Reader: {info.version}")
            result["reader_version"] = info.version
            print("Přilož SOLUM tag...")
            tag = None
            for _ in range(10):
                tag = client.search_tag()
                if tag is not None:
                    break
            if tag is None:
                raise RuntimeError("Tag nebyl nalezen.")
            print(f"SearchTag: type=0x{tag.tag_type:02X} id={tag.id_hex} bits={tag.id_bit_count}")
            result["searchtag"] = {"tag_type": f"0x{tag.tag_type:02X}", "id": tag.id_hex, "bits": tag.id_bit_count}
            if tag.id_bit_count != 64 or len(tag.id_bytes) != 8:
                raise RuntimeError("Pro tento test očekávám 64bit / 8B FeliCa ID.")
            confirm_tag(client, tag.id_bytes, 3)
            idm1, pmm1 = poll(client, 0xFFFF)
            if idm1 != tag.id_bytes:
                raise RuntimeError(f"Poll(FFFF) IDm != SearchTag ID: {hx(idm1)} != {tag.id_hex}")
            result["poll_ffff"] = {"idm": hx(idm1), "pmm": hx(pmm1)}
            system_codes = request_system_codes(client)
            result["system_codes"] = [f"0x{x:04X}" for x in system_codes]
            if NDEF_SYSTEM_CODE not in system_codes:
                raise RuntimeError("System Code 0x12FC nebyl nalezen; přímý NDEF read neprovedu.")
            idm2, pmm2 = poll(client, NDEF_SYSTEM_CODE)
            result["poll_12fc"] = {"idm": hx(idm2), "pmm": hx(pmm2), "idm_match": idm2 == idm1}
            if idm2 != idm1:
                raise RuntimeError("Poll(12FC) vrátil jiné IDm — STOP.")
            service_ok = request_service_diag(client, NDEF_RO_SERVICE)
            result["request_service_000b"] = {"result": service_ok}
            frame = build_felica_check_frame(idm2, NDEF_RO_SERVICE, 0)
            print(f"Standard FeliCa CHECK frame: {hx(frame)}")
            result["check_request_frame"] = hx(frame)
            rx = felica_tdx(client, frame, 1)
            if rx is None:
                result["read_without_encryption"] = {"status": "RESULT_FALSE", "service": "0x000B", "block": 0}
                print("ReadWithoutEncryption/CHECK: Result=false")
            else:
                parsed = parse_check_response(rx, idm2)
                result["read_without_encryption"] = parsed
                print(f"FeliCa CHECK raw RX: {hx(rx)}")
                if parsed.get("status") == "SUCCESS":
                    print("\n*** BLOCK 0 READ SUCCESS ***")
                    print(f"DATA: {parsed['block0']}")
                    print(json.dumps(parsed.get("attribute_block", {}), indent=2, ensure_ascii=False))
    except (SerialCommunicationError, ProtocolError, RuntimeError, ValueError) as exc:
        result["fatal_error"] = str(exc)
        print(f"\nERROR: {exc}")
        rc = 1
    else:
        rc = 0

    out = Path(args.json_path)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nVýsledek uložen: {out.resolve()}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
