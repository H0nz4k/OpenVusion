# SweetP — live reader position guide

SweetP is a **read-only** live meter that helps find a stable physical
alignment between an ELATEC TWN4 reader and a VUSION tag.

It does **not** write capture packages by itself (MAIN positioning feeds
capture on the second START).

## Not RF / RSSI

TWN4 Simple Protocol (`0500…`) does **not** expose verified RF RSSI.
SweetP therefore shows **read quality / reliability**, never:

- RSSI
- signal strength
- RF power %

In logs, UI, and `summary.json` the metric is a **read-quality score**
(0–100), not RSSI.

## Dual scores (v2 headless)

| Score | Role |
|---|---|
| `raw_score` | Instant quality from the latest successful probe |
| `fast_score` | EMA of raw — trend / LED overlay only |
| `stable_score` | Slower EMA — LED base band + READ acceptance |

READ acceptance and band hysteresis always use **`stable_score`**.
`fast_score` never alone accepts a READ.

### Defaults

| Key | Default |
|---|---|
| `fast_alpha` | 0.60 |
| `stable_alpha` | 0.20 |
| `trend_window_samples` | 3 |
| `trend_deadband_points_per_second` | 8.0 |
| `trend_strong_points_per_second` | 40.0 |
| `trend_min_blink_interval_ms` | 200 |
| `trend_max_blink_interval_ms` | 1000 |
| `trend_pulse_ms` | 80 |
| `no_tag_confirm_samples` | 2 |
| `sample_interval_ms` | 150 |
| `require_get_version` | false (live path; each extra RF cmd ≈ +450–500 ms) |

Older configs without these keys keep the defaults above.

## LED meaning

Base colour = **stable** band (bad=red, borderline=Y/R alternate, usable=yellow, good=green).

Trend overlay from **fast** slope (points/second):

- improving → green pulse (unless base already solid green)
- worsening → red pulse (unless base already solid red)
- deadband → no overlay

Faster absolute trend → shorter pulse period (≈1000 ms → ≈200 ms).

Restart chord (START+STOP) overrides SweetP LEDs.

## Latency budget

Typical TWN4 `SearchTag` round-trip on Pi UART ≈ **450–500 ms**.
That dominates update rate. After a sample arrives, filter + LED request
is well under 100 ms on the next main-loop tick.

First orientation LED appears after the **first valid tagged sample**
(no wait for the old 20-sample window).

## Diagnostic trace

Each MAIN positioning → READ writes `sweetp_trace.jsonl` next to
`summary.json` (included in the export TAR):

```json
{"seq":1,"t_ms":0,"raw_score":31.2,"fast_score":31.2,"stable_score":31.2,"trend":null,"band":"bad","tag_present":true,"reader_latency_ms":476.1,"accepted":false}
```

`summary.json.sweetp` keeps min/avg/max / `score_at_accept` plus
`filter_config` for reproducibility. Field `score_kind` is
`"read_quality"`.

### Tuning from a trace

1. Plot `t_ms` vs `raw_score` / `fast_score` / `stable_score`.
2. If LEDs feel laggy but `reader_latency_ms` ≈ 500 ms, the reader is the limit.
3. Raise `fast_alpha` for snappier overlay; raise `stable_alpha` carefully
   (READ gate). Widen `trend_deadband_points_per_second` if LEDs flicker.

## Legacy UI note

Touch UI still uses the rolling-window scorer for on-screen %. Headless
GPIO uses dual EMA + trend LEDs as above.
