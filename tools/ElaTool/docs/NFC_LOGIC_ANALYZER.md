# NFC Logic Analyzer

Read-only nástroj ElaToolu pro časové sledování NTAG I²C Plus 1K přes ELATEC TWN4.

## Účel

V jedné společné časové ose sekvenčně provedených měření zachytit:

1. session registry (`0xEC`–`0xED`);
2. 64bajtovou SRAM (`0xF0`–`0xFF` v pass-through mapování);
3. volitelně EEPROM stránky `0x30`–`0x37`;
4. dobu RF operací, změny mezi vzorky, chyby/NAK/timeouty.

Nástroj **nezapisuje** do tagu.

## Architektura

```text
CLI (logic-analyzer)
    → resolve_port / SimpleProtocolClient
    → NtagI2CPlus (GET_VERSION, FAST_READ, READ)
    → LogicAnalyzerCapture
         → CaptureWriter (metadata.json, timeline.jsonl, samples.csv, report.txt, errors.jsonl)
         → change detection (session / SRAM / EEPROM)
```

Moduly:

| Modul | Odpovědnost |
|---|---|
| `ntag.py` | read-only RF příkazy, CRC, NAK |
| `capture/models.py` | datový model událostí |
| `capture/changes.py` | detekce změn bajtů/bitů/rozsahů |
| `capture/writer.py` | adresář capture, JSONL/CSV/report |
| `capture/logic_analyzer.py` | časová smyčka a orchestrace |
| `cli.py` | parametrizace a spuštění |

## Časový model

- Intervaly a elapsed: `time.perf_counter_ns()` (monotónní).
- Wall-clock (`datetime.isoformat`) jen pro lidský záznam, ne pro výpočet intervalů.
- Výchozí `duration=5s`, `interval-ms=50`.
- Pokud RF operace trvá déle než interval, zaznamená se zpoždění a další vzorek se plánuje od aktuálního času — bez agresivního dohánění.

Pořadí v jednom cyklu:

```text
session → SRAM → [EEPROM 0x30–0x37 pokud --watch-eeprom]
```

Měření **nejsou simultánní**; jde o společnou časovou osu sekvenčně provedených operací.

## Paměťové oblasti

### Session registry (ověřeno v projektu)

- Příkaz: `FAST_READ` (`0x3A`) stránky `0xEC`–`0xED`.
- 8 bajtů: NC_REG, LAST_NDEF_BLOCK, SRAM_MIRROR_BLOCK, WDT_LS, WDT_MS, I2C_CLOCK_STR, NS_REG, RFU.

### SRAM přes RF (NXP datasheet NT3H2111_2211)

- V pass-through režimu (`NC_REG` bit 6 `PTHRU_ON_OFF = 1`) je 64 B SRAM mapována na RF stránky **`0xF0`–`0xFF`**.
- Příkaz: `FAST_READ 3A F0 FF` → očekáváno 64 datových bajtů.
- Mimo pass-through NFC SRAM přímo nečte; odpověď může být NAK nebo (při přesahu) nuly.
- Konstanty v kódu dokumentují zdroj a nejistotu mimo lokální měření.

### EEPROM (volitelné)

- Rozsah první verze: stránky `0x30`–`0x37` (32 B).
- Pouze při `--watch-eeprom`.
- Read-only `FAST_READ` nebo `READ`.

## Formát událostí

Každý běh vytváří adresář:

```text
captures/logic-analyzer/YYYY-MM-DD_HH-MM-SS_<UID>/
  metadata.json
  timeline.jsonl
  samples.csv
  report.txt
  errors.jsonl          # pokud nastanou chyby
  initial_eeprom.bin    # pokud --watch-eeprom
  final_eeprom.bin      # pokud --watch-eeprom
```

`timeline.jsonl`: jedna JSON událost na řádek, flush po zápisu.

Minimální pole události:

- `seq`, `t_mono_ns`, `elapsed_us`, `wall_time`
- `event_type`, `uid`
- `rf_operation`, `rf_duration_us`
- `raw_hex`, `decoded`
- `changes`, `error`

Typy událostí: `capture_started`, `tag_detected`, `get_version`, `session_sample`, `session_changed`, `sram_sample`, `sram_changed`, `eeprom_sample`, `eeprom_changed`, `rf_error`, `tag_lost`, `capture_finished`.

## Bezpečnost

Povolené RF příkazy v běžné cestě:

- SearchTag / výběr tagu
- `GET_VERSION` (`0x60`)
- `READ` (`0x30`)
- `FAST_READ` (`0x3A`)

Zakázáno:

- `WRITE`, `COMPATIBILITY_WRITE`, `FAST_WRITE`
- zápis do EEPROM / config / session / SRAM
- `PWD_AUTH` a experimentální autentizace

## Známá omezení

- Session a SRAM nejsou měřeny ve stejném okamžiku.
- SRAM přes RF je platná primárně při pass-through; jinak očekávejte chybu nebo prázdná/nulová data.
- Interval je přibližný; serializace a OS scheduling přidávají jitter.
- Bitům registrů nepřiřazujeme význam bez ověření (kromě odkazu na datasheet u `PTHRU_ON_OFF` jako kontextu adresace).

## Hypotéza (ne potvrzený fakt)

Elektronika štítku VUSION reaguje na RF aktivitu a přes I²C dynamicky mění session registry. V okně s `NC_REG≈0x7C` může být zapnutý pass-through a host může používat SRAM. Tato hypotéza vyžaduje další měření.

## Postup fyzického experimentu

1. Připoj TWN4 (typicky COM6), přilož referenční štítek.
2. Spusť:

```bash
python -m elatec_uid_tool logic-analyzer --port COM6 --duration 5 --interval-ms 50 --verbose
```

3. Předáš capture adresář (bez nutnosti commitovat do Gitu — captures jsou ignorované).

## Další plán

1. Volitelné EEPROM sledování doladit podle reálných capture.
2. Offline analýza timeline (statistika stavů, korelace session↔SRAM).
3. Sjednocení legacy skriptů jako tenkých wrapperů nad CLI.
4. Později GUI / napojení na OpenVusion Field Collector.
