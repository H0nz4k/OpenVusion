# NFC Logic Analyzer

Read-only nástroj ElaToolu pro časové sledování NTAG I²C Plus 1K přes ELATEC TWN4.

## Účel

V jedné společné časové ose sekvenčně provedených měření zachytit:

1. session registry (`0xEC`–`0xED`) — **výchozí a doporučený režim**;
2. volitelně experimentální pokus o 64B SRAM (`0xF0`–`0xFF`) — **vypnuto defaultně**;
3. volitelně EEPROM stránky `0x30`–`0x37`;
4. dobu RF operací, změny mezi vzorky, chyby/NAK/timeouty a recovery.

Nástroj **nezapisuje** do tagu a **nezapíná** pass-through ani SRAM mirror.

## Architektura

```text
CLI (logic-analyzer)
    → resolve_port / SimpleProtocolClient
    → NtagI2CPlus (GET_VERSION, FAST_READ, READ)
    → LogicAnalyzerCapture
         → nezávislé samplery (session / sram / eeprom)
         → při NAK/timeout: záznam chyby + SearchTag reselect
         → nefunkční sampler lze deaktivovat bez zastavení ostatních
         → CaptureWriter (metadata, timeline.jsonl, samples.csv, report)
```

## Časový model

- Intervaly: `time.perf_counter_ns()` (monotónní).
- Wall-clock jen pro lidský záznam.
- Výchozí `duration=5s`, `interval-ms=50`.
- Bez agresivního dohánění zmeškaných intervalů.

Pořadí v cyklu (podle zapnutých samplerů):

```text
session → [experimental SRAM] → [EEPROM 0x30–0x37]
```

## Paměťové oblasti

### Session registry (ověřeno)

- `FAST_READ 3A EC ED` → 8 bajtů.
- Fyzicky ověřeno na referenčním VUSION štítku.

### SRAM přes RF (NXP + fyzický test)

**Datasheet (NT3H2111_2211):**

- Mimo pass-through/mirror NFC nemůže SRAM přímo číst.
- Při `PTHRU_ON_OFF=1` je SRAM mapována na RF stránky **F0h–FFh**.
- Při `SRAM_MIRROR_ON_OFF=1` se SRAM zrcadlí do user memory od `SRAM_MIRROR_BLOCK`.

**Fyzický test 2026-07-31 (NTAG I²C Plus 1K, UID 04367F5A2D7280):**

- `NC_REG=0x19`, `NS_REG=0x01`
- `FAST_READ 3A F0 FF` → Type-2 NAK: *invalid address or command range*
- Následná slepá opakování způsobila lavinu timeoutů session i SRAM

**Důsledek pro nástroj:**

- `FAST_READ F0–FF` **není** fyzicky ověřená operace.
- SRAM sampling je pouze `--enable-experimental-sram`.
- Výchozí běh je session-only.
- Po prvním SRAM NAK se SRAM sampler vypne a provede se reselect.

## Recovery po chybě

Při Type-2 NAK, timeoutu nebo ztrátě tagu:

1. zaznamená se `rf_error` (a případně `tag_lost`);
2. nepokračuje se slepě stejným neplatným příkazem (SRAM NAK → disable);
3. provede se kontrolovaný `SearchTag` (`tag_reselected`);
4. ostatní funkční samplery běží dál.

## Finish status

| Status | Význam |
|---|---|
| `completed_successfully` | požadované samplery dodaly vzorky bez chyb |
| `completed_with_errors` | běh doběhl, ale byly chyby / vypnutý sampler / 0 SRAM při požadavku |
| `partial` | fatální selhání před užitečnými daty |
| `aborted` | přerušení uživatelem |

Pokud byl SRAM požadován a `sram.success == 0`, výsledek **nesmí** být
`completed_successfully`.

## Formát výstupu

```text
captures/logic-analyzer/YYYY-MM-DD_HH-MM-SS_<UID>/
  metadata.json
  timeline.jsonl
  samples.csv
  report.txt
  errors.jsonl
```

`metadata.json` / `report.txt` obsahují statistiky samplerů:

```text
session: success=N failure=M
sram:    success=N failure=M
eeprom:  success=N failure=M
```

## CLI

Bezpečný session-only test:

```bash
python -m elatec_uid_tool logic-analyzer \
  --port COM6 --duration 5 --interval-ms 50 --session-only --verbose
```

Experimentální SRAM:

```bash
python -m elatec_uid_tool logic-analyzer \
  --port COM6 --duration 5 --interval-ms 50 \
  --enable-experimental-sram --verbose
```

## Bezpečnost

Povoleno: `SearchTag`, `GET_VERSION`, `READ`, `FAST_READ`.

Zakázáno: `WRITE`, `COMPATIBILITY_WRITE`, `FAST_WRITE`, zápis registrů,
`PWD_AUTH`, zapínání pass-through/mirror z RF strany.

## Hypotéza (ne fakt)

Host MCU štítku může přes I²C dočasně zapínat pass-through (`NC_REG≈0x7C`).
Bez zápisu do session registrů to z čisté RF strany spolehlivě neaktivujeme.
Další výzkum: pozorovat session bity během RF okna; SRAM mirror adresu číst
jen pokud už je hostem zapnutá (read-only observace).

## Další plán

1. Session-only fyzické měření změn `NC_REG`/`NS_REG` bez SRAM.
2. Korelace aktivního okna s hypotézou pass-through (bez zápisu).
3. Pokud host sám zapne mirror, zvážit read-only čtení mirrorované user oblasti.
4. Offline analýza timeline.
