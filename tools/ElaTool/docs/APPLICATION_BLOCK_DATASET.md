# Application Block Dataset

Manifest a souhrn více read-only capture sad bloku `0x30`–`0x37`.

## Capture adresář

```text
captures/application-block/<timestamp>_<UID>_<label>/
  metadata.json
  samples.jsonl
  application_block.bin
  application_block.json
  application_block.txt
  report.txt
  full_dump.bin / full_dump.json   # jen --include-full-dump
  errors.jsonl                     # jen při chybách
```

`metadata.json` (schema_version ≥ 1): UID, GET_VERSION, NDEF ID (odvozené/
zadané), label, state, notes, sample_count, stable_across_samples,
`source_type=physical_tag`, `read_only=true`, tool_version, git_commit.

## Dataset výstupy

```text
captures/application-datasets/<name>/
  manifest.json
  samples.csv
  blocks.jsonl
  dataset_report.txt
  checksum_candidates.json
  checksum_candidates.csv
  checksum_report.txt
```

Každý záznam: `sample_id`, `capture_id`, UID, GET_VERSION, NDEF ID, label,
state, timestamp, `raw_block_hex`, `page_30`…`page_37`, `identifier_le`,
`stable_capture`, `source_path`, notes.

## Filtry build-application-dataset

- všechny vzorky / jen stabilní reprezentativní blok z capture;
- `--uid`, `--state`, `--label`;
- nevalidní capture se nezařadí bez upozornění ve reportu.

## Analýzy nad datasetem

- byte-position stats (constant / identifier-correlated / state-correlated / …);
- identifier correlation (LE/BE 32bit, 16bit části);
- counter/timestamp heuristiky (intra-tag časová řada);
- checksum kandidáti napříč více odlišnými bloky (omezený seznam CRC/sum/XOR).

`active_window` / RF trigger metriky sem nepatří — to řeší Trigger Analysis.
