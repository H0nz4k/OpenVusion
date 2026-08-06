#!/usr/bin/env python3
"""
ntag_session_watch.py

STRICT NON-WRITING experiment for the original SES-imagotag / VUSION
NTAG I2C Plus tag.

Goal
----
Observe whether the stock MCU reacts to an NFC field by changing NTAG I2C Plus
session-register state, especially enabling pass-through and/or placing data
into SRAM for the NFC side.

This script DOES NOT read SRAM and DOES NOT send any tag WRITE command.

Sequence per cycle:
    RF off
    wait
    SearchTag / select the same UID
    GET_VERSION
    read persistent configuration (read-only)
    repeatedly FAST_READ session pages EC..ED
    log only changes

Interesting evidence:
    NC_REG.PTHRU_ON_OFF  -> stock MCU enabled pass-through
    NC_REG.TRANSFER_DIR  -> 0 = I2C->NFC, 1 = NFC->I2C
    NS_REG.SRAM_RF_READY -> MCU/I2C side prepared SRAM data for NFC
    NS_REG.SRAM_I2C_READY-> NFC side data ready for MCU/I2C
    NS_REG.I2C_LOCKED / RF_LOCKED -> arbitration state

Important:
    NDEF_DATA_READ is a read-to-clear status bit, so repeated session reads are
    not perfectly passive with respect to that one status flag. The experiment
    remains strictly non-writing.

Run from tools/ElaTool:
    ./.venv/Scripts/python.exe ntag_session_watch.py --port COM13

Example longer run:
    ./.venv/Scripts/python.exe ntag_session_watch.py --port COM13 --cycles 3 --seconds 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from elatec_uid_tool.ntag import NtagI2CPlus, SESSION_REGISTER_NAMES  # noqa: E402
from elatec_uid_tool.protocol import SimpleProtocolClient  # noqa: E402


def hx(data: bytes) -> str:
    return data.hex(" ").upper()


def decode_nc_reg(v: int) -> dict[str, Any]:
    return {
        "raw": f"0x{v:02X}",
        "NFCS_I2C_RST_ON_OFF": bool(v & 0x80),
        "PTHRU_ON_OFF": bool(v & 0x40),
        "FD_OFF": (v >> 4) & 0x03,
        "FD_ON": (v >> 2) & 0x03,
        "SRAM_MIRROR_ON_OFF": bool(v & 0x02),
        "TRANSFER_DIR": v & 0x01,
        "TRANSFER_DIR_text": "NFC->I2C" if (v & 0x01) else "I2C->NFC",
    }


def decode_ns_reg(v: int) -> dict[str, Any]:
    return {
        "raw": f"0x{v:02X}",
        "NDEF_DATA_READ": bool(v & 0x80),
        "I2C_LOCKED": bool(v & 0x40),
        "RF_LOCKED": bool(v & 0x20),
        "SRAM_I2C_READY": bool(v & 0x10),
        "SRAM_RF_READY": bool(v & 0x08),
        "EEPROM_WR_ERR": bool(v & 0x04),
        "EEPROM_WR_BUSY": bool(v & 0x02),
        "RF_FIELD_PRESENT": bool(v & 0x01),
    }


def decode_session(raw: bytes) -> dict[str, Any]:
    regs = {
        SESSION_REGISTER_NAMES[i]: raw[i]
        for i in range(min(len(SESSION_REGISTER_NAMES), len(raw)))
    }
    return {
        "raw_hex": hx(raw),
        "registers_hex": {k: f"0x{v:02X}" for k, v in regs.items()},
        "NC_REG": decode_nc_reg(regs.get("NC_REG", 0)),
        "NS_REG": decode_ns_reg(regs.get("NS_REG", 0)),
        "LAST_NDEF_BLOCK": regs.get("LAST_NDEF_BLOCK"),
        "SRAM_MIRROR_BLOCK": regs.get("SRAM_MIRROR_BLOCK"),
        "WDT_LS": regs.get("WDT_LS"),
        "WDT_MS": regs.get("WDT_MS"),
        "I2C_CLOCK_STR": regs.get("I2C_CLOCK_STR"),
    }


def flags_line(decoded: dict[str, Any]) -> str:
    nc = decoded["NC_REG"]
    ns = decoded["NS_REG"]
    return (
        f"NC={nc['raw']} "
        f"PTHRU={int(nc['PTHRU_ON_OFF'])} "
        f"DIR={nc['TRANSFER_DIR_text']} "
        f"| NS={ns['raw']} "
        f"FIELD={int(ns['RF_FIELD_PRESENT'])} "
        f"I2C_LOCK={int(ns['I2C_LOCKED'])} "
        f"RF_LOCK={int(ns['RF_LOCKED'])} "
        f"I2C_READY={int(ns['SRAM_I2C_READY'])} "
        f"RF_READY={int(ns['SRAM_RF_READY'])}"
    )


def wait_for_tag(client: SimpleProtocolClient, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tag = client.search_tag()
        if tag is not None:
            return tag
        time.sleep(0.05)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Strict non-writing NTAG I2C Plus session-state watcher"
    )
    ap.add_argument("--port", required=True, help="e.g. COM13")
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--off-seconds", type=float, default=2.0)
    ap.add_argument("--tag-timeout", type=float, default=5.0)
    ap.add_argument("--out", default="ntag_session_watch")
    args = ap.parse_args()

    if args.cycles < 1:
        raise SystemExit("--cycles must be >= 1")
    if args.seconds <= 0 or args.interval <= 0:
        raise SystemExit("--seconds and --interval must be > 0")

    report: dict[str, Any] = {
        "strict_non_writing": True,
        "sram_read": False,
        "tag_write_commands": False,
        "notes": [
            "Session registers are read with FAST_READ EC..ED.",
            "NDEF_DATA_READ is read-to-clear and is not used as primary evidence.",
            "No SRAM page F0..FF is read.",
        ],
        "port": args.port,
        "cycles": [],
    }

    locked_uid: str | None = None

    print("=" * 78)
    print(" VUSION / NTAG I2C Plus — SESSION WATCH (STRICT NON-WRITING)")
    print("=" * 78)
    print("No tag WRITE. No SRAM read. Watching session state only.")
    print("Primary signals: PTHRU_ON_OFF, TRANSFER_DIR, SRAM_*_READY, locks.")
    print()

    try:
        with SimpleProtocolClient(args.port, timeout=2.0) as client:
            try:
                print("Reader:", client.get_version_string())
            except Exception as exc:
                print("Reader version unavailable:", exc)

            for cycle_idx in range(1, args.cycles + 1):
                print()
                print(f"--- CYCLE {cycle_idx}/{args.cycles} ---")
                cycle: dict[str, Any] = {
                    "cycle": cycle_idx,
                    "events": [],
                    "samples": [],
                }
                report["cycles"].append(cycle)

                print(f"RF OFF for {args.off_seconds:.1f}s ...")
                try:
                    client.set_rf_off()
                except Exception as exc:
                    cycle["events"].append({
                        "event": "rf_off_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    print("RF OFF warning:", exc)

                time.sleep(args.off_seconds)

                print("RF ON / SearchTag ...")
                tag = wait_for_tag(client, args.tag_timeout)
                if tag is None:
                    cycle["events"].append({"event": "tag_timeout"})
                    print("ERROR: tag not found")
                    continue

                uid = tag.id_hex.upper()
                print(
                    f"SearchTag: type=0x{tag.tag_type:02X} "
                    f"uid={uid} bits={tag.id_bit_count}"
                )

                if locked_uid is None:
                    locked_uid = uid
                    report["locked_uid"] = uid
                elif uid != locked_uid:
                    raise RuntimeError(
                        f"UID CHANGED: expected {locked_uid}, got {uid}; aborting"
                    )

                ntag = NtagI2CPlus(client)

                version = ntag.get_version()
                print("GET_VERSION:", hx(version.raw))
                cycle["get_version_hex"] = hx(version.raw)
                cycle["is_ntag_i2c_plus_1k"] = version.is_ntag_i2c_plus_1k

                try:
                    cfg = ntag.read_configuration_registers()
                    cfg_hex = {
                        f"0x{k:02X}": hx(v)
                        for k, v in cfg.items()
                    }
                    cycle["configuration"] = cfg_hex
                    print("Config:", cfg_hex)
                except Exception as exc:
                    cycle["configuration_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    print("Config read warning:", exc)

                print()
                print(
                    f"Watching session for {args.seconds:.1f}s "
                    f"@ {args.interval*1000:.0f} ms ..."
                )

                start = time.monotonic()
                previous_raw: bytes | None = None
                sample_index = 0
                evidence = {
                    "pthru_seen": False,
                    "sram_rf_ready_seen": False,
                    "sram_i2c_ready_seen": False,
                    "i2c_locked_seen": False,
                    "rf_locked_seen": False,
                }

                while (time.monotonic() - start) < args.seconds:
                    t_rel = time.monotonic() - start
                    try:
                        raw = ntag.read_session_registers()
                        decoded = decode_session(raw)

                        nc = decoded["NC_REG"]
                        ns = decoded["NS_REG"]
                        evidence["pthru_seen"] |= bool(nc["PTHRU_ON_OFF"])
                        evidence["sram_rf_ready_seen"] |= bool(ns["SRAM_RF_READY"])
                        evidence["sram_i2c_ready_seen"] |= bool(ns["SRAM_I2C_READY"])
                        evidence["i2c_locked_seen"] |= bool(ns["I2C_LOCKED"])
                        evidence["rf_locked_seen"] |= bool(ns["RF_LOCKED"])

                        sample = {
                            "index": sample_index,
                            "t_s": round(t_rel, 6),
                            **decoded,
                        }
                        cycle["samples"].append(sample)

                        if previous_raw is None:
                            print(f"[{sample_index:04d}] {t_rel:7.3f}s BASE  {flags_line(decoded)}")
                        elif raw != previous_raw:
                            print(f"[{sample_index:04d}] {t_rel:7.3f}s CHANGE {flags_line(decoded)}")
                            cycle["events"].append({
                                "event": "session_change",
                                "sample": sample_index,
                                "t_s": round(t_rel, 6),
                                "from_hex": hx(previous_raw),
                                "to_hex": hx(raw),
                            })

                        previous_raw = raw
                        sample_index += 1

                    except Exception as exc:
                        cycle["events"].append({
                            "event": "sample_error",
                            "sample": sample_index,
                            "t_s": round(t_rel, 6),
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                        print(
                            f"[{sample_index:04d}] {t_rel:7.3f}s ERROR "
                            f"{type(exc).__name__}: {exc}"
                        )
                        break

                    time.sleep(args.interval)

                cycle["evidence"] = evidence
                cycle["sample_count"] = len(cycle["samples"])

                print()
                print("Cycle evidence:")
                for key, val in evidence.items():
                    print(f"  {key}: {val}")

                if evidence["pthru_seen"]:
                    print("  >>> STOCK MCU ENABLED PASS-THROUGH during RF field.")
                if evidence["sram_rf_ready_seen"]:
                    print("  >>> STRONG: MCU/I2C side made SRAM data ready for NFC.")
                if evidence["sram_i2c_ready_seen"]:
                    print("  >>> NFC->I2C SRAM-ready state observed.")
                if not any(evidence.values()):
                    print("  No pass-through/arbitration activity observed in this window.")

            try:
                client.set_rf_off()
            except Exception:
                pass

    except Exception as exc:
        report["fatal_error"] = f"{type(exc).__name__}: {exc}"
        print()
        print("FATAL:", report["fatal_error"])

    out = Path(f"{args.out}.json")
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("JSON:", out.resolve())
    print()
    print("Interpretation:")
    print("  PTHRU=1          -> stock MCU enabled NTAG SRAM pass-through")
    print("  RF_READY=1       -> MCU/I2C wrote data into SRAM for NFC side")
    print("  I2C_READY=1      -> SRAM contains NFC-side data for MCU/I2C")
    print("  I2C_LOCK/RF_LOCK -> active interface arbitration")
    print("  NDEF_DATA_READ is intentionally ignored as primary evidence (read-to-clear).")

    return 1 if "fatal_error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
