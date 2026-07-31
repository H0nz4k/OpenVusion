# Storage Format

## Layout

```text
/var/lib/hwsniff/
  captures/
    YYYY-MM-DD/
      YYYY-MM-DD_HH-MM-SS_<UID>/
        metadata.json
        application_block.bin / .json   # pages 0x30–0x37
        session.bin / session.json      # session registers 0xEC–0xED
        dump.bin / dump.json            # full EEPROM 0x00–0xE1
        hashes.json                     # SHA-256 of artifacts
        report.txt
  index.csv
  index.jsonl
```

One START session = one long-lived reader process: detect (incl. already-present
tag via RF wake) → full export → wait for removal → next tag.

## Export TAR (one tag → one archive)

After each successful sniff of **one tag**, every artifact from that capture is
packed into a single uncompressed tar:

```text
/home/sniffer/capture/DDMMYYYY_HH_MM.tar
```

Example: `/home/sniffer/capture/31072026_05_15.tar`

If two tags finish in the same minute: `…_1.tar`, `…_2.tar`, …

Configurable via `collector.export_bundle_root` (set `null` to disable).
Original files under `/var/lib/hwsniff/captures/` are kept.

## Integrity

Before UI shows CAPTURE OK / SAFE:

1. required files written
2. files re-opened
3. SHA-256 recorded in `hashes.json`
4. index append
5. flush

Partial failures are marked in metadata (`finish_status`) and never claimed OK.

## Export

```bash
/opt/Sniff/scripts/export-data.sh /media/usb
```

Copies captures + index, writes export manifest, verifies SHA-256. Never deletes SD data.
