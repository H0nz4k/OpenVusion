from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Nastavení
# ---------------------------------------------------------------------------

PORT = "COM6"
DURATION_SECONDS = 5.0
SAMPLE_INTERVAL_SECONDS = 0.05   # 20 vzorků za sekundu
OUTPUT_DIR = Path("captures") / "session-monitor"

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if not SRC_DIR.exists():
    raise RuntimeError(f"Nenalezen adresář src: {SRC_DIR}")

sys.path.insert(0, str(SRC_DIR))

from elatec_uid_tool.ntag import NtagI2CPlus
from elatec_uid_tool.protocol import SerialCommunicationError, SimpleProtocolClient


REGISTER_NAMES = (
    "NC_REG",
    "LAST_NDEF_BLOCK",
    "SRAM_MIRROR_BLOCK",
    "WDT_LS",
    "WDT_MS",
    "I2C_CLOCK_STR",
    "NS_REG",
    "RFU",
)


def read_session_registers(ntag: NtagI2CPlus) -> bytes:
    """Přečte session registry 0xEC–0xED přes read-only FAST_READ."""
    data = ntag.transceive(bytes((0x3A, 0xEC, 0xED)))

    if len(data) != 8:
        raise SerialCommunicationError(
            "FAST_READ 0xEC–0xED měl vrátit 8 datových bajtů, "
            f"přišlo {len(data)}: {data.hex(' ').upper()}"
        )

    return data


def changed_bits(old: int, new: int) -> list[int]:
    """Vrátí čísla bitů, které se mezi dvěma hodnotami změnily."""
    mask = old ^ new
    return [bit for bit in range(8) if mask & (1 << bit)]


def format_changed_bits(old: int, new: int) -> str:
    bits = changed_bits(old, new)
    return ",".join(str(bit) for bit in bits) if bits else ""


def print_change(
    elapsed: float,
    previous: bytes | None,
    current: bytes,
) -> None:
    timestamp = f"{elapsed:8.3f}s"

    if previous is None:
        print(
            f"{timestamp}  "
            f"NC_REG=0x{current[0]:02X}  "
            f"NS_REG=0x{current[6]:02X}  "
            f"RAW={current.hex(' ').upper()}"
        )
        return

    if previous == current:
        return

    print(
        f"{timestamp}  "
        f"NC_REG 0x{previous[0]:02X}->0x{current[0]:02X}  "
        f"NS_REG 0x{previous[6]:02X}->0x{current[6]:02X}  "
        f"RAW={current.hex(' ').upper()}"
    )

    for index, (old, new) in enumerate(zip(previous, current)):
        if old == new:
            continue

        page = 0xEC if index < 4 else 0xED
        offset = index if index < 4 else index - 4

        print(
            f"           0x{page:02X}[{offset}] "
            f"{REGISTER_NAMES[index]}: "
            f"0x{old:02X} ({old:08b}) -> "
            f"0x{new:02X} ({new:08b}); "
            f"změněné bity: {format_changed_bits(old, new)}"
        )


def save_results(
    uid: str,
    version: bytes,
    samples: list[dict],
    started_at: str,
) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    safe_uid = uid.lower().replace(" ", "")
    stem = datetime.now().strftime(
        f"ntag-{safe_uid}-session-%Y-%m-%d_%H-%M-%S"
    )

    csv_path = OUTPUT_DIR / f"{stem}.csv"
    json_path = OUTPUT_DIR / f"{stem}.json"

    fieldnames = [
        "sample",
        "elapsed_seconds",
        "wall_time",
        "read_duration_ms",
        "raw_hex",
        *REGISTER_NAMES,
        "changed",
        "changed_registers",
    ]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for sample in samples:
            row = {
                "sample": sample["sample"],
                "elapsed_seconds": sample["elapsed_seconds"],
                "wall_time": sample["wall_time"],
                "read_duration_ms": sample["read_duration_ms"],
                "raw_hex": sample["raw_hex"],
                "changed": sample["changed"],
                "changed_registers": ",".join(sample["changed_registers"]),
            }

            for index, name in enumerate(REGISTER_NAMES):
                row[name] = f"0x{sample['bytes'][index]:02X}"

            writer.writerow(row)

    json_document = {
        "schema": 1,
        "started_at": started_at,
        "uid": uid,
        "get_version": version.hex(" ").upper(),
        "port": PORT,
        "duration_seconds_requested": DURATION_SECONDS,
        "sample_interval_seconds_requested": SAMPLE_INTERVAL_SECONDS,
        "sample_count": len(samples),
        "read_only": True,
        "command": "FAST_READ 3A EC ED",
        "samples": samples,
    }

    json_path.write_text(
        json.dumps(json_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return csv_path, json_path


def main() -> None:
    print(f"Projekt:           {PROJECT_ROOT}")
    print(f"Python balíčky:    {SRC_DIR}")
    print(f"Otevírám čtečku:   {PORT}")
    print(f"Doba monitorování: {DURATION_SECONDS:.1f} s")
    print(
        "Cílová frekvence:  "
        f"{1 / SAMPLE_INTERVAL_SECONDS:.1f} vzorků/s"
    )
    print("Režim:             pouze GET_VERSION / FAST_READ")
    print()

    started_at = datetime.now().astimezone().isoformat()
    samples: list[dict] = []

    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()

        if tag is None:
            raise RuntimeError(
                "NFC tag nebyl nalezen. Přilož štítek ke čtečce."
            )

        uid = tag.id_hex
        print(f"UID:               {uid}")
        print(f"TagType:           0x{tag.tag_type:02X}")
        print(f"ID bits:           {tag.id_bit_count}")

        ntag = NtagI2CPlus(client)
        version = ntag.get_version()

        print(f"GET_VERSION:       {version.raw.hex(' ').upper()}")
        print()
        print("Změny session registrů")
        print("======================")

        start = time.perf_counter()
        next_sample_at = start
        previous: bytes | None = None
        sample_number = 0

        while True:
            now = time.perf_counter()
            elapsed = now - start

            if elapsed >= DURATION_SECONDS:
                break

            if now < next_sample_at:
                time.sleep(next_sample_at - now)

            read_started = time.perf_counter()
            current = read_session_registers(ntag)
            read_finished = time.perf_counter()

            elapsed = read_finished - start
            sample_number += 1

            changed_registers = []
            if previous is not None:
                changed_registers = [
                    REGISTER_NAMES[index]
                    for index, (old, new) in enumerate(zip(previous, current))
                    if old != new
                ]

            sample = {
                "sample": sample_number,
                "elapsed_seconds": round(elapsed, 6),
                "wall_time": datetime.now().astimezone().isoformat(),
                "read_duration_ms": round(
                    (read_finished - read_started) * 1000,
                    3,
                ),
                "raw_hex": current.hex(" ").upper(),
                "bytes": list(current),
                "changed": previous is not None and previous != current,
                "changed_registers": changed_registers,
            }
            samples.append(sample)

            print_change(elapsed, previous, current)
            previous = current

            next_sample_at += SAMPLE_INTERVAL_SECONDS

            # Pokud čtení trvá déle než interval, nepokoušíme se dohánět
            # několik zmeškaných vzorků v rychlé smyčce.
            current_time = time.perf_counter()
            if next_sample_at < current_time:
                next_sample_at = current_time + SAMPLE_INTERVAL_SECONDS

    csv_path, json_path = save_results(
        uid=uid,
        version=version.raw,
        samples=samples,
        started_at=started_at,
    )

    unique_states = {
        sample["raw_hex"]
        for sample in samples
    }
    changed_samples = sum(
        1 for sample in samples
        if sample["changed"]
    )

    print()
    print("Souhrn")
    print("------")
    print(f"Počet vzorků:       {len(samples)}")
    print(f"Unikátní stavy:     {len(unique_states)}")
    print(f"Zaznamenané změny:  {changed_samples}")
    print(f"CSV:                {csv_path}")
    print(f"JSON:               {json_path}")
    print()
    print("Hotovo. Nebyl proveden žádný zápis do tagu.")


if __name__ == "__main__":
    main()
