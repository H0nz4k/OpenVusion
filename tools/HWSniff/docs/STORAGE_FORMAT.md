# Storage Format

## Layout

```text
/var/lib/hwsniff/
  captures/
    YYYY-MM-DD/
      YYYY-MM-DD_HH-MM-SS_<UID>/
        summary.json
        application.json / eeprom.json / …
        events.jsonl
        …
  export/
    DDMMYYYY_HH_MM.tar          # primary export bundle (authoritative)
  index.csv
  index.jsonl

/var/log/hwsniff/
  hwsniff.log
  collector.jsonl
  …

/home/sniffer/exports/          # optional mirror of finished .tar (same filename)
  DDMMYYYY_HH_MM.tar
```

One START → one tag → one capture directory → one export archive.

## SweetP stats in `summary.json`

When READ is accepted from POSITIONING, an immutable SweetP snapshot is merged
into `summary.json` (and therefore into the export TAR) under `sweetp`:

```json
"sweetp": {
  "score_at_accept": 78.513,
  "band_at_accept": "good",
  "minimum": 27.699,
  "maximum": 78.523,
  "average": 59.214,
  "sample_count": 123,
  "started_at": "…",
  "accepted_at": "…"
}
```

Only numeric tagged samples from the current positioning cycle are included.
Captures without SweetP positioning keep backward-compatible empty/null stats.

## Export TAR (one tag → one archive)

After each successful sniff of **one tag**, every artifact from that capture is
packed into a single uncompressed tar (atomic write via `.tmp` + rename):

```text
/var/lib/hwsniff/export/DDMMYYYY_HH_MM.tar
```

Example: `/var/lib/hwsniff/export/04082026_22_15.tar`

If two tags finish in the same minute: `…_1.tar`, `…_2.tar`, …

### Config (`collector`)

| Key | Default | Notes |
|-----|---------|-------|
| `export_bundle_root` | `/var/lib/hwsniff/export` | Primary; set `null` to disable packing |
| `export_bundle_mirror_root` | `null` (code) / `/home/sniffer/exports` (Pi example) | Identical copy after primary success |
| `include_logs_in_bundle` | `false` | When `true`, include regular files from `log_root` under `logs/` |

Capture files are stored as **flattened basenames** in the archive (legacy layout).
Log files keep their relative path under `logs/` (symlinks / sockets / devices skipped).
Missing `log_root` only logs a warning — export still succeeds.

Mirror failures are logged; the primary archive is never deleted.

Original files under `/var/lib/hwsniff/captures/` are kept.

## Integrity

Before UI / LEDs show CAPTURE OK:

1. required files written
2. files re-opened
3. SHA-256 recorded where applicable
4. index append
5. export pack (+ optional mirror)

Partial failures are marked in metadata (`finish_status`) and never claimed OK.

## USB bulk export

```bash
/opt/Sniff/scripts/export-data.sh /media/usb
```

Copies captures + index, writes export manifest, verifies SHA-256. Never deletes SD data.
