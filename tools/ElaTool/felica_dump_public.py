#!/usr/bin/env python3
"""
felica_dump_public.py

STRICTNĚ READ-ONLY dump veřejně čitelného NFC Forum Type 3 prostoru
SOLUM/FeliCa tagu přes ELATEC TWN4 Simple Protocol.

Ověřený postup:
  SearchTag
  -> Poll(FFFF)
  -> RequestSystemCode
  -> Poll(12FC)
  -> CHECK / Read Without Encryption na service 0x000B

Skript:
- přečte Attribute Information Block (block 0),
- z Nmaxb odvodí počet veřejných datových bloků,
- přečte blocky 1..Nmaxb JEDEN PO DRUHÉM,
- před každým uložením kontroluje IDm ve FeliCa response,
- nikdy nepoužívá service 0x0009 ani WRITE command,
- uloží JSON report a raw binární dump.

Pokud Attribute Block uvádí Ln=0, data v blocích 1..Nmaxb nejsou aktivní
NDEF message. Skript je označí pouze jako raw veřejně čitelný prostor.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from elatec_uid_tool.protocol import SimpleProtocolClient, SerialCommunicationError, ProtocolError

EXPECTED_TAG_TYPE = 0x85
NDEF_SYSTEM_CODE = 0x12FC
NDEF_RO_SERVICE = 0x000B


def hx(data: bytes) -> str:
    return data.hex().upper()


def poll(client: SimpleProtocolClient, system_code: int) -> tuple[bytes, bytes]:
    payload = client._request(b"\x1D\x04" + system_code.to_bytes(2, "little"))
    if not payload:
        raise RuntimeError("FeliCa_Poll: prázdná odpověď.")
    if payload[0] == 0:
        raise RuntimeError(f"FeliCa_Poll(0x{system_code:04X}): Result=false.")
    if payload[0] != 1 or len(payload) < 17:
        raise RuntimeError(f"FeliCa_Poll: neočekávaná odpověď: {hx(payload)}")
    return payload[1:9], payload[9:17]


def request_system_codes(client: SimpleProtocolClient) -> list[int]:
    payload = client._request(b"\x1D\x03\x08")
    if not payload:
        raise RuntimeError("RequestSystemCode: prázdná odpověď.")
    if payload[0] == 0:
        return []
    if payload[0] != 1 or len(payload) < 2:
        raise RuntimeError(f"RequestSystemCode: neočekávaná odpověď {hx(payload)}")
    count = payload[1]
    need = 2 + count * 2
    if len(payload) < need:
        raise RuntimeError(f"RequestSystemCode: krátká odpověď {hx(payload)}")
    return [int.from_bytes(payload[2 + 2*i:4 + 2*i], "little") for i in range(count)]


def build_check_frame(idm: bytes, block_number: int) -> bytes:
    if len(idm) != 8:
        raise ValueError("IDm musí mít 8 bajtů.")
    if not 0 <= block_number <= 0xFF:
        raise ValueError("Block number musí být 0..255.")
    body = (
        b"\x06"
        + idm
        + b"\x01"
        + NDEF_RO_SERVICE.to_bytes(2, "little")
        + b"\x01"
        + bytes([0x80, block_number])
    )
    return bytes([1 + len(body)]) + body


def felica_tdx(client: SimpleProtocolClient, frame: bytes) -> bytes | None:
    cmd = b"\x1D\x00" + bytes([len(frame)]) + frame + b"\xFF\xFF\x01"
    payload = client._request(cmd)
    if not payload:
        raise RuntimeError("FeliCa_TDX: prázdná odpověď.")
    if payload[0] == 0:
        return None
    if payload[0] != 1:
        raise RuntimeError(f"FeliCa_TDX: neplatný Result: {hx(payload)}")
    rest = payload[1:]
    if not rest:
        raise RuntimeError("FeliCa_TDX: chybí RX data.")
    if rest[0] == len(rest) - 1:
        return rest[1:]
    if len(rest) >= 2:
        n16 = int.from_bytes(rest[:2], "little")
        if n16 == len(rest) - 2:
            return rest[2:]
    if rest[0] == len(rest):
        return rest
    raise RuntimeError("FeliCa_TDX: neznámé kódování success payloadu: " + hx(payload))


def parse_check_response(rx: bytes, expected_idm: bytes) -> tuple[bytes, dict]:
    original = rx
    if rx and rx[0] == 0x07:
        rx = bytes([len(rx) + 1]) + rx
    if len(rx) < 13:
        raise RuntimeError(f"CHECK response příliš krátká: {hx(original)}")
    frame_len = rx[0]
    response_code = rx[1]
    idm = rx[2:10]
    sf1, sf2, block_count = rx[10], rx[11], rx[12]
    data = rx[13:]
    meta = {
        "raw_hex": hx(original),
        "frame_len": frame_len,
        "response_code": f"0x{response_code:02X}",
        "idm": hx(idm),
        "idm_match": idm == expected_idm,
        "status_flag1": f"0x{sf1:02X}",
        "status_flag2": f"0x{sf2:02X}",
        "number_of_blocks": block_count,
    }
    if response_code != 0x07:
        raise RuntimeError(f"Neočekávaný response code: {hx(original)}")
    if idm != expected_idm:
        raise RuntimeError(f"IDm mismatch během dumpu: {hx(idm)} != {hx(expected_idm)}")
    if sf1 != 0 or sf2 != 0:
        raise RuntimeError(f"FeliCa status error SF1=0x{sf1:02X} SF2=0x{sf2:02X}")
    if block_count != 1:
        raise RuntimeError(f"Očekáván 1 block, přišlo {block_count}.")
    if len(data) != 16:
        raise RuntimeError(f"Očekáváno 16 B, přišlo {len(data)}.")
    return data, meta


def parse_attribute_block(data: bytes) -> dict:
    if len(data) != 16:
        raise ValueError("Attribute block musí mít 16 B.")
    checksum_expected = int.from_bytes(data[14:16], "big")
    checksum_actual = sum(data[:14]) & 0xFFFF
    return {
        "valid_checksum": checksum_actual == checksum_expected,
        "version_raw": f"0x{data[0]:02X}",
        "version_major": data[0] >> 4,
        "version_minor": data[0] & 0x0F,
        "nbr": data[1],
        "nbw": data[2],
        "nmaxb": int.from_bytes(data[3:5], "big"),
        "writef": f"0x{data[9]:02X}",
        "rwflag": f"0x{data[10]:02X}",
        "ndef_length": int.from_bytes(data[11:14], "big"),
        "checksum_expected": f"0x{checksum_expected:04X}",
        "checksum_actual": f"0x{checksum_actual:04X}",
    }


def wait_for_tag(client: SimpleProtocolClient):
    print("Přilož SOLUM / FeliCa tag...")
    for _ in range(20):
        tag = client.search_tag()
        if tag is not None:
            return tag
        time.sleep(0.1)
    raise RuntimeError("Tag nebyl nalezen.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict read-only dump veřejného Type-3 service 0x000B.")
    ap.add_argument("--port", required=True, help="COM port, např. COM13")
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--max-block", type=int, default=None, help="Volitelný hard limit. Default = Nmaxb z Attribute Blocku.")
    ap.add_argument("--out", default="felica_public_dump", help="Prefix výstupních souborů.")
    args = ap.parse_args()

    if args.max_block is not None and not 0 <= args.max_block <= 255:
        print("ERROR: --max-block musí být 0..255")
        return 2

    report = {
        "strict_read_only": True,
        "service_code": "0x000B",
        "writes_implemented": False,
        "port": args.port,
        "blocks": [],
    }

    print("=" * 72)
    print(" SOLUM / FeliCa Type 3 — PUBLIC SPACE DUMP (STRICT READ-ONLY)")
    print("=" * 72)
    print("Pouze service 0x000B / Read Without Encryption.")
    print("Žádný WRITE příkaz není implementován.\n")

    try:
        with SimpleProtocolClient(args.port, timeout=args.timeout) as client:
            info = client.read_info()
            print(f"Reader: {info.version}")
            report["reader_version"] = info.version
            tag = wait_for_tag(client)
            print(f"SearchTag: type=0x{tag.tag_type:02X} id={tag.id_hex} bits={tag.id_bit_count}")
            report["searchtag"] = {"tag_type": f"0x{tag.tag_type:02X}", "id": tag.id_hex, "bits": tag.id_bit_count}
            if tag.tag_type != EXPECTED_TAG_TYPE:
                print(f"VAROVÁNÍ: očekáváno tag_type 0x{EXPECTED_TAG_TYPE:02X}, přišlo 0x{tag.tag_type:02X}.")
            if tag.id_bit_count != 64 or len(tag.id_bytes) != 8:
                raise RuntimeError("Očekáván 64bit / 8B FeliCa target.")

            idm1, _ = poll(client, 0xFFFF)
            if idm1 != tag.id_bytes:
                raise RuntimeError("Poll(FFFF) IDm != SearchTag ID.")
            codes = request_system_codes(client)
            print("SystemCodes:", [f"0x{x:04X}" for x in codes])
            if NDEF_SYSTEM_CODE not in codes:
                raise RuntimeError("System Code 0x12FC není dostupný.")
            idm2, pmm2 = poll(client, NDEF_SYSTEM_CODE)
            if idm2 != idm1:
                raise RuntimeError("Poll(12FC) IDm mismatch — STOP.")
            report["felica"] = {"idm": hx(idm2), "pmm": hx(pmm2), "system_codes": [f"0x{x:04X}" for x in codes]}

            rx0 = felica_tdx(client, build_check_frame(idm2, 0))
            if rx0 is None:
                raise RuntimeError("Block 0 ReadWithoutEncryption => Result=false.")
            block0, meta0 = parse_check_response(rx0, idm2)
            attr = parse_attribute_block(block0)
            print("Block 0:", hx(block0))
            print("Attribute:")
            print(json.dumps(attr, indent=2, ensure_ascii=False))
            if not attr["valid_checksum"]:
                raise RuntimeError("Attribute Block checksum nesedí.")

            max_block = attr["nmaxb"]
            if args.max_block is not None:
                max_block = min(max_block, args.max_block)
            report["attribute_block"] = attr
            report["active_ndef_length"] = attr["ndef_length"]
            report["note"] = (
                "Ln=0 means no active NDEF message; blocks >0 are raw public service contents, not asserted to be current NDEF payload."
                if attr["ndef_length"] == 0
                else "Blocks contain the public Type-3 NDEF storage area."
            )
            blocks = [block0]
            report["blocks"].append({"block": 0, "data_hex": hx(block0), "meta": meta0, "role": "attribute_information_block"})

            print(f"\nČtu blocky 1..{max_block} po jednom...")
            for block_no in range(1, max_block + 1):
                rx = felica_tdx(client, build_check_frame(idm2, block_no))
                if rx is None:
                    print(f"[{block_no:02d}] Result=false -> STOP")
                    report["blocks"].append({"block": block_no, "status": "RESULT_FALSE"})
                    break
                data, meta = parse_check_response(rx, idm2)
                blocks.append(data)
                nonzero = any(data)
                ascii_preview = "".join(chr(b) if 32 <= b <= 126 else "." for b in data)
                print(f"[{block_no:02d}] {hx(data)}  {'NONZERO' if nonzero else 'zero':7s}  {ascii_preview}")
                report["blocks"].append({
                    "block": block_no,
                    "status": "SUCCESS",
                    "data_hex": hx(data),
                    "nonzero": nonzero,
                    "ascii_preview": ascii_preview,
                    "meta": meta,
                })
            bin_data = b"".join(blocks)

    except (SerialCommunicationError, ProtocolError, RuntimeError, ValueError) as exc:
        report["fatal_error"] = str(exc)
        print("\nERROR:", exc)
        rc = 1
        bin_data = b""
    else:
        rc = 0

    json_path = Path(f"{args.out}.json")
    bin_path = Path(f"{args.out}.bin")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if bin_data:
        bin_path.write_bytes(bin_data)
    print(f"\nJSON: {json_path.resolve()}")
    if bin_data:
        print(f"BIN : {bin_path.resolve()} ({len(bin_data)} B)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
