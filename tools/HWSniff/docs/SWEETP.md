# SweetP — reader position guide

SweetP is a **read-only** touchscreen mode that helps find a stable physical
alignment between an ELATEC TWN4 reader and a VUSION tag.

It is **not** a field capture workflow and **does not** write capture packages
into `/var/lib/hwsniff/captures` or append the global index.

## Purpose

1. Place the reader near the tag.
2. Slowly move / rotate until SweetP reports **POSITION OK**.
3. Remember that position for later field collection with **START**.

## Not RF / RSSI

TWN4 transport used here does **not** expose a verified RSSI or RF power metric.
SweetP therefore never shows:

- RSSI
- signal strength
- RF power percentages

Displayed **GOOD / USABLE / POOR** is a **communication quality score** derived
from read stability (success ratio, consecutive successes, UID/data
consistency, timeouts, reselects) — not field strength.

## Probe sequence (read-only)

Each attempt:

1. `SearchTag` / select
2. UID
3. `GET_VERSION`
4. `READ` page `0x00`
5. Application block `0x30`–`0x37` via `FAST_READ`

Default: 10 attempts, ~100 ms apart.

## POSITION OK criteria

- success ratio ≥ `minimum_success_ratio` (default 0.9)
- consecutive successes ≥ `minimum_consecutive_successes` (default 5)
- stable UID across successful attempts
- consistent `GET_VERSION` and page `0x00`
- application block exactly 32 bytes and consistent
- no excessive timeouts / reselects / reader reconnects

Otherwise: **MOVE READER** (unstable).

## NFC safety

Strict read-only. No WRITE / FAST_WRITE / PWD_AUTH / SRAM / pass-through.

## Logging

Metrics go only to application logs (`hwsniff.log` / `collector.jsonl`).
Successful SweetP runs do **not** increase the capture OK counter.

## Known limits

- Quality labels are communication scores, not RF calibration.
- Needs a working TWN4 USB path (same autodetection as field mode).
- Does not replace field collection; use START after finding a good pose.
