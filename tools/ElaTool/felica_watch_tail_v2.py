#!/usr/bin/env python3
"""
felica_watch_tail_v2.py

STRICT READ-ONLY watcher pro SOLUM/FeliCa tag.
Robustní verze:
- před každým sample provede Poll(0x12FC),
- ověří stejné IDm,
- čte bloky 54,55,56,
- při Result=false provede re-poll a retry,
- nepadá na jediném transientním RF failu,
- průběžně ukládá JSON i při chybě / Ctrl+C,
- žádný WRITE příkaz není implementován.

Použití:
    ./.venv/Scripts/python.exe felica_watch_tail_v2.py --port COM13 --seconds 120 --interval 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from elatec_uid_tool.protocol import SimpleProtocolClient

SYSTEM_CODE = 0x12FC
SERVICE_CODE = 0x000B
WATCH_BLOCKS = (54, 55, 56)


def hx(b: bytes) -> str:
    return b.hex().upper()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def poll(client: SimpleProtocolClient, system_code: int) -> tuple[bytes, bytes]:
    payload = client._request(b"\x1D\x04" + system_code.to_bytes(2, "little"))
    if not payload:
        raise RuntimeError("Poll: empty response")
    if payload[0] == 0:
        raise RuntimeError("Poll: Result=false")
    if payload[0] != 1 or len(payload) < 17:
        raise RuntimeError(f"Poll: invalid response {hx(payload)}")
    return payload[1:9], payload[9:17]


def build_check_frame(idm: bytes, block_number: int) -> bytes:
    body = (
        b"\x06"
        + idm
        + b"\x01"
        + SERVICE_CODE.to_bytes(2, "little")
        + b"\x01"
        + bytes([0x80, block_number])
    )
    return bytes([1 + len(body)]) + body


def tdx_read_once(client: SimpleProtocolClient, idm: bytes, block_number: int) -> bytes | None:
    frame = build_check_frame(idm, block_number)
    cmd = b"\x1D\x00" + bytes([len(frame)]) + frame + b"\xFF\xFF\x01"
    payload = client._request(cmd)
    if not payload:
        raise RuntimeError(f"Block {block_number}: empty response")
    if payload[0] == 0:
        return None
    if payload[0] != 1:
        raise RuntimeError(f"Block {block_number}: invalid Result {payload[0]:02X}")

    rest = payload[1:]
    if rest and rest[0] == len(rest) - 1:
        rx = rest[1:]
    elif len(rest) >= 2 and int.from_bytes(rest[:2], "little") == len(rest) - 2:
        rx = rest[2:]
    elif rest and rest[0] == len(rest):
        rx = rest
    else:
        raise RuntimeError(f"Block {block_number}: unknown TDX wrapper {hx(payload)}")

    if rx and rx[0] == 0x07:
        rx = bytes([len(rx) + 1]) + rx
    if len(rx) < 29:
        raise RuntimeError(f"Block {block_number}: short FeliCa response {hx(rx)}")

    response_code = rx[1]
    rx_idm = rx[2:10]
    sf1, sf2 = rx[10], rx[11]
    count = rx[12]
    data = rx[13:]

    if response_code != 0x07:
        raise RuntimeError(f"Block {block_number}: response_code=0x{response_code:02X}")
    if rx_idm != idm:
        raise RuntimeError(f"Block {block_number}: IDm mismatch {hx(rx_idm)} != {hx(idm)}")
    if sf1 != 0 or sf2 != 0:
        raise RuntimeError(f"Block {block_number}: SF1=0x{sf1:02X} SF2=0x{sf2:02X}")
    if count != 1 or len(data) != 16:
        raise RuntimeError(f"Block {block_number}: invalid block count/data length")
    return data


def read_block_resilient(
    client: SimpleProtocolClient,
    expected_idm: bytes,
    block_number: int,
    retries: int,
) -> tuple[bytes | None, int, list[str]]:
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            data = tdx_read_once(client, expected_idm, block_number)
            if data is not None:
                return data, attempt, errors
            errors.append(f"attempt {attempt}: Result=false")
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")

        try:
            idm, _ = poll(client, SYSTEM_CODE)
            if idm != expected_idm:
                raise RuntimeError(f"re-poll IDm mismatch {hx(idm)} != {hx(expected_idm)}")
        except Exception as exc:
            errors.append(f"re-poll after attempt {attempt}: {exc}")
        time.sleep(0.05)
    return None, retries, errors


def save_log(path: Path, log: dict) -> None:
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Robust read-only watcher for FeliCa blocks 54-56.")
    ap.add_argument("--port", required=True)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--out", default="felica_tail_watch_v2.json")
    args = ap.parse_args()

    out = Path(args.out)
    log = {
        "strict_read_only": True,
        "writes_implemented": False,
        "port": args.port,
        "system_code": "0x12FC",
        "service_code": "0x000B",
        "blocks": list(WATCH_BLOCKS),
        "started_utc": now_utc(),
        "samples": [],
        "events": [],
    }
    baseline: dict[str, str] | None = None
    rc = 0

    try:
        with SimpleProtocolClient(args.port, timeout=1.5) as client:
            info = client.read_info()
            print("Reader:", info.version)
            log["reader_version"] = info.version

            tag = None
            for _ in range(20):
                tag = client.search_tag()
                if tag is not None:
                    break
                time.sleep(0.1)
            if tag is None:
                raise RuntimeError("Tag not found")

            expected_idm = tag.id_bytes
            print(f"SearchTag: type=0x{tag.tag_type:02X} id={tag.id_hex}")
            idm, pmm = poll(client, SYSTEM_CODE)
            if idm != expected_idm:
                raise RuntimeError(f"Initial Poll IDm mismatch: {hx(idm)} != {tag.id_hex}")

            print("IDm:", hx(idm))
            print("PMm:", hx(pmm))
            print(f"Watching blocks {WATCH_BLOCKS} for {args.seconds}s (retry={args.retries}) ...")
            log["idm"] = hx(idm)
            log["pmm"] = hx(pmm)

            started = time.monotonic()
            sample_no = 0
            while time.monotonic() - started < args.seconds:
                sample_started = time.monotonic()
                try:
                    idm_now, _ = poll(client, SYSTEM_CODE)
                    if idm_now != expected_idm:
                        raise RuntimeError(f"cycle poll IDm mismatch {hx(idm_now)} != {hx(expected_idm)}")
                except Exception as exc:
                    event = {"timestamp_utc": now_utc(), "sample": sample_no, "type": "poll_error", "error": str(exc)}
                    log["events"].append(event)
                    print(f"[{sample_no:03d}] POLL ERROR: {exc}")
                    save_log(out, log)
                    sample_no += 1
                    time.sleep(args.interval)
                    continue

                current: dict[str, str] = {}
                sample_errors: list[dict] = []
                for block_no in WATCH_BLOCKS:
                    data, attempts, errors = read_block_resilient(client, expected_idm, block_no, args.retries)
                    if data is None:
                        sample_errors.append({"block": block_no, "attempts": attempts, "errors": errors})
                    else:
                        current[str(block_no)] = hx(data)
                        if errors:
                            sample_errors.append({"block": block_no, "attempts": attempts, "recovered": True, "errors": errors})

                complete = len(current) == len(WATCH_BLOCKS)
                changed = complete and baseline is not None and current != baseline
                row = {
                    "sample": sample_no,
                    "timestamp_utc": now_utc(),
                    "complete": complete,
                    "blocks": current,
                    "changed_vs_previous_complete_sample": changed,
                    "errors": sample_errors,
                }
                log["samples"].append(row)

                if not complete:
                    print(f"[{sample_no:03d}] incomplete sample ({len(current)}/{len(WATCH_BLOCKS)} blocks)")
                elif baseline is None:
                    print(f"[{sample_no:03d}] baseline")
                    for b in WATCH_BLOCKS:
                        print(f"  {b}: {current[str(b)]}")
                    baseline = current
                elif changed:
                    print(f"[{sample_no:03d}] *** CHANGE ***")
                    for b in WATCH_BLOCKS:
                        old = baseline[str(b)]
                        new = current[str(b)]
                        if old != new:
                            print(f"  {b}: {old} -> {new}")
                    baseline = current
                else:
                    recovered = any(e.get("recovered") for e in sample_errors)
                    suffix = " (recovered transient)" if recovered else ""
                    print(f"[{sample_no:03d}] no change{suffix}")
                    baseline = current

                save_log(out, log)
                sample_no += 1
                elapsed = time.monotonic() - sample_started
                time.sleep(max(0.0, args.interval - elapsed))

    except KeyboardInterrupt:
        print("\nCtrl+C — ukládám dosavadní log.")
        log["stopped"] = "keyboard_interrupt"
        rc = 130
    except Exception as exc:
        print("\nERROR:", exc)
        log["fatal_error"] = str(exc)
        rc = 1
    finally:
        log["finished_utc"] = now_utc()
        save_log(out, log)
        print("Saved:", out.resolve())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
