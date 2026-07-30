# NFC Logic Analyzer — Progress Log

Pracovní záznam vývoje read-only NFC Logic Analyzeru pro NTAG I²C Plus.

---

## 2026-07-31 — Úvodní inspekce

### Aktuální struktura projektu

```text
tools/ElaTool/
├── src/elatec_uid_tool/
│   ├── protocol.py          # SerialAsciiTransport, SimpleProtocolClient, SearchTag, ISO14443_3_TDX
│   ├── ntag.py              # CRC_A, NtagI2CPlus (GET_VERSION, READ, config 0xE8–0xE9)
│   ├── ntag_puvodni.py      # legacy: NtagDump, dump(), širší EEPROM API
│   ├── analyzer.py          # UID bitový analyzátor (AppBlaster), ne NFC dump
│   ├── cli.py               # subcommands: ports, reader-info, capture, analyze, …
│   ├── ports.py             # resolve_port / auto ELATEC VID 09D8
│   ├── commands.py          # reexport příkazů
│   └── …
├── tests/                   # unittest: protocol, analyzer, workflow
├── docs/
├── captures/                # logic-analyzer/, nfc/, session-monitor/, sram-monitor/
├── monitor_ntag_session.py  # legacy session monitor (FAST_READ 3A EC ED)
├── read_ntag_session_registers.py
├── dump_vusion_ntag.py      # volá ntag.dump() — metoda je v ntag_puvodni, ne v ntag.py
└── …
```

Balíček: `elatec_uid_tool` v0.2.0, závislost `pyserial>=3.5`, Python >=3.10.
Branch: `main` (working tree čistý kromě nesouvisejících `notes/*`).

### Existující použitelné komponenty

| Komponenta | Stav | Použití pro Logic Analyzer |
|---|---|---|
| `SimpleProtocolClient.search_tag` | ověřeno | detekce UID |
| `SimpleProtocolClient.iso14443_3_tdx` | ověřeno | RF transport |
| `NtagI2CPlus.transceive` / CRC_A / Type-2 NAK | ověřeno | společná RF vrstva |
| `NtagI2CPlus.get_version` | ověřeno | metadata capture |
| `NtagI2CPlus.read_block` / `read_page` | ověřeno | EEPROM 0x30–0x37 |
| `NtagI2CPlus.read_configuration_registers` | ověřeno | volitelná metadata |
| Session FAST_READ `3A EC ED` | ověřeno ve skriptech | přesunout do `ntag.py` |
| `resolve_port` | ověřeno | `--port` / `auto` |
| `captures/` + `.gitignore` | připraveno | výstupy mimo Git |

### Duplicity a dočasné skripty

- `read_ntag_configuration.py` vs `read_ntag_configuration_src.py` / `_auto.py` — duplicitní CLI.
- `read_ntag_session_registers.py` a `monitor_ntag_session.py` — lokální kopie `read_session_registers()`.
- `ntag.py` vs `ntag_puvodni.py` — dump/analýza zůstala v legacy souboru; aktuální `ntag.py` nemá `dump()` / `NtagDump` / `fast_read()`.
- `protocol_puvodni.py` — starší varianta protokolu.
- Root skripty zatím **nemažeme**; označit jako legacy po integraci CLI.

### Známé technické dluhy

1. Chybí centralizované `fast_read()` a `read_session_registers()` v `ntag.py`.
2. Chybí read-only čtení 64B SRAM.
3. `dump_vusion_ntag.py` / `analyze_vusion_ntag_dump.py` importují API z `ntag`, které tam není (žije v `ntag_puvodni`).
4. Session monitor nemá společnou časovou osu se SRAM.
5. Namespace zůstává `elatec_uid_tool` (záměrně).

### Ověřená RF adresace (zdroj pravdy)

**Session registry (ověřeno měřením + skripty):**

- Příkaz: `FAST_READ` `3A EC ED` → 8 bajtů.
- Stránky `0xEC`–`0xED`: NC_REG … NS_REG, RFU.

**SRAM přes RF (NXP NT3H2111_2211 datasheet, ne lokální měření):**

- V pass-through režimu (`PTHRU_ON_OFF = 1`, bit 6 `NC_REG`) je 64B SRAM mapována na RF stránky **`0xF0`–`0xFF`** (16 × 4 B).
- Mimo pass-through NFC nemůže SRAM přímo číst; `FAST_READ` mimo povolenou oblast → NAK, nebo nuly u přesahu.
- I²C adresa SRAM (`F8h`–`FBh` bloky) není RF adresace.
- Pozorované stavy: `NC_REG=0x19` (PTHRU off) / `NC_REG=0x7C` (PTHRU on) — hypotéza pro okno aktivity ~1,15 s.

### Návrh minimální architektury

```text
elatec_uid_tool/
  ntag.py                 # + fast_read, read_session_registers, read_sram
  capture/
    models.py             # CaptureEvent, metadata
    changes.py            # detekce změn session/SRAM/EEPROM
    writer.py             # JSONL/CSV/report/adresář
    logic_analyzer.py     # časová smyčka (sekvenční osa)
  cli.py                  # subcommand logic-analyzer
```

Oddělení: transport → NTAG příkazy → sampling → change detect → serializace → CLI.

Strategie cyklu: `session → SRAM → [volitelně EEPROM 0x30–0x37]`.
Formulace: „společná časová osa sekvenčně provedených měření“.

### Plán implementace po fázích

1. **Docs** — progress + `NFC_LOGIC_ANALYZER.md` (architektura, bezpečnost, adresace).
2. **ntag API** — `fast_read`, session, SRAM (read-only), konstanty se zdrojem.
3. **Capture jádro** — model událostí, writer, logic analyzer smyčka, CLI.
4. **Testy** — fake transport, change detect, JSONL, CLI parser, NAK.
5. **Docs usage** — README, CHANGELOG Unreleased, závěr progress logu.

---

## 2026-07-31 — První milník implementován

### Provedené změny

- Přidány read-only metody `fast_read`, `read_session_registers`, `read_sram`,
  `read_eeprom_range` do `ntag.py` včetně konstant RF mapování SRAM `0xF0`–`0xFF`.
- Nový balíček `elatec_uid_tool.capture` (models, changes, writer, logic_analyzer).
- CLI subcommand `logic-analyzer` s parametry `--port`, `--duration`,
  `--interval-ms`, `--output-dir`, `--watch-eeprom`, `--verbose`.
- Výstup: `metadata.json`, `timeline.jsonl`, `samples.csv`, `report.txt`,
  volitelně EEPROM bin a `errors.jsonl`.
- Strategie cyklu: `session → SRAM → [EEPROM 0x30–0x37]`.
- Unit testy pro change detection, writer, NTAG NAK/SRAM, CLI a scripted capture.

### Změněné / nové soubory

- `src/elatec_uid_tool/ntag.py`
- `src/elatec_uid_tool/capture/*`
- `src/elatec_uid_tool/cli.py`
- `src/elatec_uid_tool/commands.py`
- `src/elatec_uid_tool/logic_analyzer_commands.py`
- `tests/test_capture_changes.py`
- `tests/test_capture_writer.py`
- `tests/test_ntag_readonly.py`
- `tests/test_logic_analyzer.py`
- `tests/test_workflow.py`
- `docs/NFC_LOGIC_ANALYZER.md`
- `docs/NFC_LOGIC_ANALYZER_PROGRESS.md`
- `docs/ARCHITECTURE.md`
- `README.md`, kořenový `README.md`, `CHANGELOG.md`
- `captures/logic-analyzer/.gitkeep`

### Spuštěné testy

```text
python -m unittest discover -s tests -v
scripts/check_version.py
```

Výsledek: **22 tests OK**, verze konzistentní `0.2.0`.

### Nevyřešené otázky

1. Lokální fyzické ověření, že `FAST_READ F0–FF` na referenčním VUSION štítku
   vrací 64 B během aktivního okna (`NC_REG=0x7C`).
2. Chování mimo pass-through (NAK vs. nuly) na tomto konkrétním tagu.
3. Zda EEPROM `0x30–0x37` vůbec dynamicky mění během RF okna.
4. `ntag.dump` / `NtagDump` stále žijí jen v `ntag_puvodni.py` (mimo tento milník).

### Doporučený další krok

Fyzický test:

```bash
python -m elatec_uid_tool logic-analyzer --port COM6 --duration 5 --interval-ms 50 --verbose
```

Pak zkontrolovat `timeline.jsonl` na `session_changed` a případné `sram_sample` /
`sram_changed` v aktivním okně.

---

## 2026-07-31 — Oprava po fyzickém testu SRAM NAK

### Příčina

Capture `2026-07-31_00-32-02_04367F5A2D7280`:

1. Session `FAST_READ EC–ED` OK (`NC_REG=0x19`).
2. `FAST_READ F0–FF` → Type-2 NAK invalid address.
3. Slepá opakování SRAM i session → timeout lavina (16 RF chyb).
4. `finish_reason=completed` byl zavádějící (0 platných SRAM stavů).

NXP: RF mapa F0–FF platí jen při pass-through. Nástroj pass-through
nezapíná (read-only) → přímé čtení SRAM není v běžném stavu dostupné.

### Provedené změny

- Výchozí režim: session-only; SRAM jen `--enable-experimental-sram`.
- Po SRAM NAK: `sampler_disabled` + okamžitý `SearchTag` recovery.
- Session sampler pokračuje bez laviny timeoutů.
- `finish_status`: completed_successfully / completed_with_errors /
  partial / aborted.
- Report/metadata: success/failure počty per sampler.
- Dokumentace opravená: F0–FF není fyzicky ověřený přístup.

### Spuštěné testy

```text
python -m unittest discover -s tests -v
```

Výsledek: **25 tests OK**.

### Doporučený další fyzický test

```bash
python -m elatec_uid_tool logic-analyzer --port COM6 --duration 5 --interval-ms 50 --session-only --verbose
```

---

## 2026-07-31 — Trigger Analysis + Application Block Analysis

### Provedené změny

- Nový CLI `trigger-analysis` se scénáři select-only / get-version /
  read-page-00 / read-application-block / read-session /
  get-version-then-session / repeated-session-only.
- Best-effort settle + reselect; contaminated/inconclusive značení;
  závěry observed / repeatable / probable (bez confirmed trigger).
- Výstupy `captures/trigger-analysis/...` (metadata, timeline.jsonl,
  scenarios.csv, report).
- Application block analyzer pro EEPROM `0x30`–`0x37` (tag / JSON / BIN),
  compare více dumpů, checksum kandidáti, confirmed LE NDEF ID match.
- CLI: `application-block`, `analyze-application-block`,
  `compare-application-blocks`.
- Dokumentace `TRIGGER_ANALYSIS.md`, `APPLICATION_BLOCK_ANALYSIS.md`.

### Testy

```text
python -m unittest discover -s tests -v
python -m compileall -q src
```

Výsledek: **38 tests OK**, compileall OK. Ověřen načtený `dump_A.json`
→ page `0x33 = C9 D0 2C AA` confirmed LE match.

### Doporučený další krok

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose
python -m elatec_uid_tool application-block --port COM6
```

---

## 2026-07-31 — Trigger baseline redesign (first-sample)

### Fyzické zjištění

`--all` běh: první FAST_READ EC ED → baseline `0x19/0x01`; další session
read (~50–120 ms) → active `0x7C/0x29`; po ~1,1 s návrat do baseline;
po reselectu jeden baseline vzorek byl označen `stable=false` /
`contaminated=true` → scénář skončil před triggerem; všech 21 opakování
inconclusive bez `rf_duration_us` / samples.

### Oprava

- First-sample baseline: jeden `0x19/0x01` je platný start.
- Metody: `baseline_observed`, `baseline_confirmed_after_return`,
  `baseline_stable_by_multiple_reads` (poslední není povinná).
- Settle `baseline → active → baseline` = `completed_active_cycle` + `--guard-ms`.
- Po reselectu max. jeden pre-trigger session probe; žádná série před triggerem.
- `contaminated` jen pro active/unknown pre-trigger, nedokončený cyklus, RF chybu.
- `select-only`: SearchTag je trigger (`rf_operation`).
- `repeated-session-only`: první session read = trigger t=0.
- Nová pole: `measurement_interference_possible`, `baseline_method`,
  `baseline_sample_count`, `pre_trigger_state`, `trigger_executed`.

### Testy

```text
python -m unittest discover -s tests -v
python -m compileall -q src
```

### Doporučený fyzický retest

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose
```

---

## 2026-07-31 — Intermediate state + general RF association

### Fyzické zjištění (capture `2026-07-31_01-37-24_04367F5A2D7280`)

- Baseline redesign OK: 21/21 executed, 0 contaminated, ~1,15 s okno.
- Mezistav `NC=0x7C NS=0x41` před kanonickým `0x7C/0x29` rozbíjel detekci
  (`read-page-00` a get-version #2 falešně inconclusive).
- Stejný cyklus u většiny RF scénářů → obecná RF/select asociace, ne magic cmd.
- SearchTag `rf_duration_us` ~824 ms = transport/API, ne čistý RF frame.

### Oprava

- Stavy: baseline / intermediate / active / other (bez „NC=0x7C ⇒ active“).
- Metriky: `first_nonbaseline_us`, `intermediate_enter_us`, `active_enter_us`,
  `total_nonbaseline_window_us`, …; `active_window_us` = total non-baseline.
- Agregace: `transition_repetitions`, `canonical_active_repetitions`,
  `intermediate_repetitions`, `state_counts`.
- Závěry: observed / repeatable / **general RF association**;
  globální věta o host wake-up asociaci.

### Testy

```text
python -m unittest discover -s tests -v
python -m compileall -q src
```

### Doporučený fyzický retest

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose
```
