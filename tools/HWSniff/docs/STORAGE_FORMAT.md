# Storage Format

## Layout

```text
/var/lib/hwsniff/
  captures/
    YYYY-MM-DD/
      YYYY-MM-DD_HH-MM-SS_<UID>/
        metadata.json
        dump.bin            # optional full EEPROM
        application_block.bin
        application_block.json
        session.bin         # optional
        hashes.json         # SHA-256 of artifacts
        report.txt
  index.csv
  index.jsonl
```

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
