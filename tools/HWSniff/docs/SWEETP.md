# SweetP — live reader position guide

SweetP is a **read-only** live meter that helps find a stable physical
alignment between an ELATEC TWN4 reader and a VUSION tag.

It does **not** write capture packages and does **not** append the field index.

## Not RF / RSSI

TWN4 does **not** expose verified RSSI / RF power in the current stack.
SweetP therefore shows **position quality / read stability**, never:

- RSSI
- signal strength
- RF power %

## How to use

1. From READY tap **SWEETP**.
2. Slowly move / rotate the reader relative to the tag.
3. Watch live quality %, trend (LEPŠÍ / HORŠÍ / STABILNÍ), and the bar.
4. When **POSITION OK** appears (stable high quality for a few seconds),
   you may still improve the pose or tap **HOTOVO**.
5. **ZRUŠIT** always stops the worker and frees the serial port.

## Quality score (0–100)

Rolling window (default 20 samples):

| Component | Default weight |
|---|---|
| Read success rate | 60 % |
| Latency score | 25 % |
| UID consistency | 15 % |

If `use_latency` is false: success 80 % + UID consistency 20 %.

Latency is normalized between `latency_good_ms` and `latency_bad_ms`
(timeout / slow → 0).

## Trend

Compares short-window average quality vs older part of the main window.
Delta ≥ `trend_threshold` → LEPŠÍ; ≤ −threshold → HORŠÍ; else STABILNÍ.
`trend_hold_ms` hysteresis reduces flicker.

## POSITION OK

Requires enough samples, quality ≥ `good_quality_threshold`, high UID
consistency, held for `good_hold_ms`. Does **not** auto-exit — live
meter continues; quality drop clears POSITION OK.

## Live probe (read-only)

Default sample (~150 ms): `SearchTag` (+ optional `GET_VERSION`).
Optional page 0x00 / application block via config (slower on Pi 3).

## Config keys (`sweetp`)

`sample_interval_ms`, `window_size`, `short_window_size`, `trend_threshold`,
`trend_hold_ms`, `good_quality_threshold`, `poor_quality_threshold`,
`good_hold_ms`, `latency_good_ms`, `latency_bad_ms`, `weight_*`,
`use_latency`, `ui_update_ms`, `require_get_version`, `require_page_00`,
`require_application_block`.

Older configs with only `probe_interval_ms` still work.

## Reader errors

Disconnect / open failure → **SWEETP READER ERROR** with **ZNOVU** / **ZRUŠIT**.
SweetP and field START remain mutually exclusive.
