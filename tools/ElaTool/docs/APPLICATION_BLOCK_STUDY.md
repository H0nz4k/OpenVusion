# Application Block Study Workflow

Read-only experimentální workflow pro systematický sběr a porovnání
EEPROM aplikačního bloku `0x30`–`0x37` na VUSION / NTAG I²C Plus 1K.

## Kontext po Trigger Analysis

Trigger Analysis dospěl k závěru:

> Results are consistent with a general RF/select-associated host wake-up,
> not a command-specific trigger.

Další fáze se zaměřuje na **EEPROM data** (aplikační blok), nikoli na hledání
unikátního RF magic command.

## Bezpečnost

Striktně READ-ONLY. Zakázáno: WRITE, COMPATIBILITY_WRITE, FAST_WRITE,
PWD_AUTH, změna config/session registrů, pass-through, SRAM mirror,
EEPROM/SRAM write.

Povoleno: SearchTag, GET_VERSION, READ, FAST_READ (ověřený EEPROM rozsah),
read-only session registry, read-only full EEPROM dump.

## Potvrzená fakta

```text
UID:         04367F5A2D7280
GET_VERSION: 00 04 04 05 02 02 13 03
NDEF ID:     AA2CD0C9
page 0x33:   C9 D0 2C AA
```

Označení: **confirmed little-endian identifier match**.

Hypotézy (ne fakta): header na `0x30`, reserved `0x31–0x32`,
flags/counters `0x34–0x36`, checksum na `0x37`.

## Doporučené stavy (label/state metadata)

Stejný tag:

- `baseline-idle`, `before-rf`, `after-session-monitor`
- `after-trigger-analysis`, `after-application-read`
- `after-power-cycle` (pokud fyzicky možné)
- `before-display-update`, `after-display-update`
- `after-original-system-contact`
- `delayed-5min`, `delayed-1h`

Různé tagy: `same-model-tag-01` … / jiný model.

Label/state jsou **uživatelská experimentální metadata**, ne důkaz významu.

## CLI přehled

```bash
# Opakovaný capture jednoho stavu
python -m elatec_uid_tool capture-application-block \
  --port COM6 --label reference-before-rf --state before-rf \
  --notes "Referenční tag před RF testem"

# Dataset z více capture adresářů
python -m elatec_uid_tool build-application-dataset \
  captures/application-block \
  --output captures/application-datasets/reference-study

# Intra-tag (stejný UID, různé stavy)
python -m elatec_uid_tool compare-application-captures \
  capture_before capture_after --mode intra-tag

# Inter-tag / dataset analýza
python -m elatec_uid_tool compare-application-dataset \
  captures/application-datasets/reference-study --mode inter-tag

# Manuální plán experimentu (bez RF zápisu)
python -m elatec_uid_tool application-study-plan \
  --name vusion-reference-study \
  --output captures/application-studies/vusion-reference-study
```

## Formulace výsledků

- confirmed structural match
- observed correlation
- repeatable correlation
- candidate field
- insufficient evidence
- contradicted hypothesis

Nikdy high-confidence význam pole z jednoho tagu.

Podrobnosti datasetu: [APPLICATION_BLOCK_DATASET.md](APPLICATION_BLOCK_DATASET.md).
