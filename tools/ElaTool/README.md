# ElaTool

`ElaTool` je NFC výzkumný, diagnostický a servisní modul projektu
**OpenVusion**. Komunikuje přes čtečku **ELATEC TWN4** a obsahuje nástroje
pro analýzu štítků **SES-imagotag VUSION 2.6 BWR GU140** s čipem
**NTAG I²C Plus 1K**.

> Výchozí režim všech současných diagnostických nástrojů je pouze pro čtení.
> Zápisové experimenty do EEPROM, konfigurace nebo SRAM zde zatím nejsou
> součástí běžného workflow.

## Aktuální schopnosti

- detekce ELATEC čtečky a NFC tagu;
- načtení UID a typu tagu;
- `GET_VERSION`;
- Type 2 Tag příkazy `READ` a `FAST_READ`;
- výpočet a kontrola `CRC_A`;
- rozpoznání jed bajtových Type-2 NAK odpovědí;
- bezpečný dump EEPROM NTAG I²C Plus 1K;
- export dumpu do BIN, JSON a TXT;
- analýza nenulových oblastí, NDEF, ASCII, entropie a kandidátních ID;
- porovnání dvou NTAG dumpů;
- čtení konfiguračních registrů;
- čtení a časové sledování session registrů;
- **NFC Logic Analyzer** — výchozí bezpečný session-only režim;
- experimentální (neověřený) pokus o RF čtení SRAM, vypnutý ve výchozím stavu;
- **Trigger Analysis** — asociace RF operací s přechody session registrů;
- **Application Block Analysis** — pasivní rozbor EEPROM `0x30`–`0x37`.

## Potvrzený testovaný tag

```text
UID:         04367F5A2D7280
GET_VERSION: 00 04 04 05 02 02 13 03
Typ:         NTAG I²C Plus 1K
EEPROM:      stránky 0x00–0xE1
```

NDEF obsahuje URL ve tvaru:

```text
https://nfc.imagotag.com/AA2CD0C9
```

V aplikační oblasti EEPROM byl nalezen stejný identifikátor v little-endian:

```text
C9 D0 2C AA
```

## Struktura

```text
ElaTool/
├── src/
│   └── elatec_uid_tool/
│       ├── protocol.py
│       ├── ntag.py
│       ├── analyzer.py
│       ├── cli.py
│       ├── capture/          # NFC Logic Analyzer
│       └── ...
├── tests/
├── docs/
│   ├── NFC_LOGIC_ANALYZER.md
│   └── NFC_LOGIC_ANALYZER_PROGRESS.md
├── scripts/
├── captures/
│   └── logic-analyzer/
├── pyproject.toml
├── requirements.txt
└── README.md
```

Balíček si zatím zachovává původní název `elatec_uid_tool`, aby migrace
nezměnila funkční importy. Přejmenování na `elatool` je vhodné provést až
samostatným refaktoringem s testy.

## Instalace na Windows

Otevři Git Bash nebo PowerShell v adresáři:

```text
OpenVusion/tools/ElaTool
```

Vytvoř virtuální prostředí:

```bash
python -m venv .venv
```

Git Bash:

```bash
source .venv/Scripts/activate
```

PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Nainstaluj projekt:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

Pokud editable instalace nepoužívá závislosti z projektu:

```bash
python -m pip install -r requirements.txt
```

## Základní ověření

Připoj ELATEC TWN4, přilož štítek a zkontroluj port, typicky `COM6`.

Spuštění existujícího CLI:

```bash
python -m elatec_uid_tool
```

Případně pomocné Windows skripty:

```text
elaUIDtool.bat
run_interactive.bat
run_tests.bat
```

## NFC Logic Analyzer (read-only)

Sleduje session registry na **společné časové ose sekvenčně provedených
měření**. Výchozí režim je **session-only**. SRAM přes RF je experimentální
a ve výchozím stavu vypnutá.

### Požadavky

- ELATEC TWN4 s PRS Simple Protocol firmware;
- Python 3.10+ a nainstalovaný `elatec-uid-tool`;
- štítek NTAG I²C Plus (testováno na VUSION 2.6 BWR GU140).

### Bezpečný fyzický test (session-only)

```bash
python -m elatec_uid_tool logic-analyzer \
  --port COM6 \
  --duration 5 \
  --interval-ms 50 \
  --session-only \
  --verbose
```

Bez `--session-only` je chování stejné: SRAM zůstává vypnutá, dokud ji
výslovně nezapneš.

### Experimentální SRAM (neověřeno)

```bash
python -m elatec_uid_tool logic-analyzer \
  --port COM6 \
  --duration 5 \
  --interval-ms 50 \
  --enable-experimental-sram \
  --verbose
```

CLI vypíše varování. Fyzický test 2026-07-31 ukázal, že
`FAST_READ 3A F0 FF` na NTAG I²C Plus 1K s `NC_REG=0x19` vrací Type-2 NAK
(*invalid address or command range*) a může rozbít následující RF session.
Při NAK nástroj SRAM sampler **deaktivuje**, provede `SearchTag` recovery
a pokračuje v session samplingu.

Volitelné EEPROM `0x30`–`0x37`:

```bash
python -m elatec_uid_tool logic-analyzer --port COM6 --session-only --watch-eeprom
```

| Parametr | Výchozí | Význam |
|---|---|---|
| `--port` | `auto` | COM port nebo automatická detekce ELATEC |
| `--duration` | `5` | délka capture v sekundách |
| `--interval-ms` | `50` | cílový interval vzorkování |
| `--output-dir` | `captures/logic-analyzer` | kořen výstupů |
| `--session-only` | vypnuto* | pouze session registry |
| `--enable-experimental-sram` | vypnuto | experimentální FAST_READ `0xF0`–`0xFF` |
| `--watch-eeprom` | vypnuto | sledovat EEPROM `0x30`–`0x37` |
| `--verbose` | vypnuto | živý výpis změn |

\*Bez experimental flagu je SRAM stejně vypnutá (bezpečný default).

### Výstup

```text
captures/logic-analyzer/YYYY-MM-DD_HH-MM-SS_<UID>/
  metadata.json
  timeline.jsonl
  samples.csv
  report.txt
  errors.jsonl            # jen při chybách
  initial_eeprom.bin      # jen s --watch-eeprom
  final_eeprom.bin        # jen s --watch-eeprom
```

`finish_status` v metadata/report:

- `completed_successfully`
- `completed_with_errors`
- `partial`
- `aborted`

Capture adresáře jsou v Gitu ignorované.

### Omezení měření / SRAM

- Podle NXP datasheetu je RF přístup k SRAM (`0xF0`–`0xFF`) platný jen při
  zapnutém pass-through; alternativně přes SRAM mirror do user memory.
- Tento nástroj **nezapisuje** registry a **nezapíná** pass-through ani mirror.
- Fyzický test: `FAST_READ F0–FF` byl odmítnut jako invalid address.
- Proto SRAM není součástí výchozího workflow.

### Hypotéza

Elektronika štítku může při RF aktivitě měnit session registry a dočasně
zapínat pass-through. Jde o **hypotézu**, nikoli potvrzený fakt.

Podrobnosti: [docs/NFC_LOGIC_ANALYZER.md](docs/NFC_LOGIC_ANALYZER.md).

## Samostatné diagnostické nástroje (legacy)

Některé výzkumné funkce zůstávají jako samostatné Python skripty
v kořeni ElaToolu. Po zavedení `logic-analyzer` je považujte za
legacy / compatibility wrappers — zatím se nemažou.

### Dump NTAG

```bash
python dump_vusion_ntag.py
```

### Analýza dumpu

```bash
python analyze_vusion_ntag_dump.py
```

### Porovnání dumpů

```bash
python compare_ntag_dumps.py <prvni.json> <druhy.json>
```

### Konfigurační registry

```bash
python read_ntag_configuration.py
```

nebo podle aktuální funkční varianty:

```bash
python read_ntag_configuration_src.py
```

### Session registry

Jednorázové čtení:

```bash
python read_ntag_session_registers.py
```

Časový monitor:

```bash
python monitor_ntag_session.py
```

Výstup monitoru se ukládá do:

```text
captures/session-monitor/
```

## Dosavadní nález ze session monitoru

Byly zachyceny dva stabilní stavy:

```text
výchozí: NC_REG=0x19, NS_REG=0x01
aktivní: NC_REG=0x7C, NS_REG=0x29
```

Aktivní stav vznikl přibližně 50 ms po prvním přístupu, trval asi
1,15 sekundy a poté se vrátil do výchozího stavu. To podporuje hypotézu,
že elektronika štítku reaguje na RF aktivitu a dynamicky pracuje se
session registry nebo SRAM.

## Trigger Analysis

Hledá asociace mezi RF operacemi a přechodem session registrů
`0x19/0x01 → 0x7C/0x29`. Neprohlašuje confirmed kauzalitu.

Baseline používá **first-sample** model: jeden platný `0x19/0x01` stačí.
Více consecutive baseline reads není povinné — session read sám spouští
aktivní okno. Po settle cyklu `baseline → active → baseline` následuje
krátká `--guard-ms` prodleva. Scénář `select-only` měří `SearchTag` jako
trigger; `repeated-session-only` bere první session read jako t=0.

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose

python -m elatec_uid_tool trigger-analysis \
  --port COM6 --scenario get-version --repetitions 3 --guard-ms 200 --verbose
```

Výstup: `captures/trigger-analysis/<timestamp>_<UID>/`
(`metadata.json`, `timeline.jsonl`, `scenarios.csv`, `report.txt`).

Podrobnosti: [docs/TRIGGER_ANALYSIS.md](docs/TRIGGER_ANALYSIS.md).

## Application Block Analysis (`0x30`–`0x37`)

Pasivní read-only rozbor aplikačního EEPROM bloku.

```bash
python -m elatec_uid_tool application-block --port COM6

python -m elatec_uid_tool analyze-application-block dump.json

python -m elatec_uid_tool compare-application-blocks dump1.json dump2.json
```

Potvrzený fakt: NDEF `AA2CD0C9` == stránka `0x33` `C9 D0 2C AA`
(little-endian).

Podrobnosti: [docs/APPLICATION_BLOCK_ANALYSIS.md](docs/APPLICATION_BLOCK_ANALYSIS.md).

## Plán dalšího vývoje

1. fyzický běh Trigger Analysis na COM6 a vyhodnocení scénářů;
2. porovnání application block napříč více stavy štítku;
3. offline analýza logic-analyzer timeline;
4. sjednotit legacy skripty jako tenké wrappery nad CLI.

## Bezpečnost

Dokud nebude zápisová část navržena a otestována:

- nepoužívat příkazy `WRITE` nebo `COMPATIBILITY_WRITE`;
- neměnit konfigurační registry;
- neměnit session registry;
- neprovádět experimenty na jediném dostupném referenčním štítku;
- před budoucím zápisem vždy pořídit EEPROM dump a ověřit UID.

## Původ projektu

ElaTool vznikl migrací samostatného projektu `elaUIDtool`. Jeho původní
README je archivováno zde:

```text
docs/migration/README_elaUIDtool_original.md
```
