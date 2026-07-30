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
- read-only čtení 64B SRAM (RF mapování pass-through `0xF0`–`0xFF`);
- **NFC Logic Analyzer** — společná časová osa session + SRAM (+ volitelně EEPROM).

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

Sleduje session registry a 64B SRAM na **společné časové ose sekvenčně
provedených měření** (ne simultánní záznam). První verze je CLI-only a
striktně read-only.

### Požadavky

- ELATEC TWN4 s PRS Simple Protocol firmware;
- Python 3.10+ a nainstalovaný `elatec-uid-tool`;
- štítek NTAG I²C Plus (testováno na VUSION 2.6 BWR GU140).

### Spuštění

```bash
python -m elatec_uid_tool logic-analyzer --port COM6
```

S parametry:

```bash
python -m elatec_uid_tool logic-analyzer \
  --port COM6 \
  --duration 5 \
  --interval-ms 50 \
  --output-dir captures/logic-analyzer \
  --verbose
```

Volitelné sledování aplikačního EEPROM bloku `0x30`–`0x37`:

```bash
python -m elatec_uid_tool logic-analyzer --port COM6 --watch-eeprom
```

| Parametr | Výchozí | Význam |
|---|---|---|
| `--port` | `auto` | COM port nebo automatická detekce ELATEC |
| `--duration` | `5` | délka capture v sekundách |
| `--interval-ms` | `50` | cílový interval vzorkování |
| `--output-dir` | `captures/logic-analyzer` | kořen výstupů |
| `--watch-eeprom` | vypnuto | sledovat EEPROM `0x30`–`0x37` |
| `--verbose` | vypnuto | živý výpis změn |

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

Capture adresáře jsou v Gitu ignorované. Pro další analýzu stačí předat
celý adresář capture.

### Omezení měření

- Session a SRAM se čtou sekvenčně v pořadí `session → SRAM → [EEPROM]`.
- SRAM přes RF (`FAST_READ 0xF0–0xFF`) je podle NXP datasheetu dostupná
  v pass-through režimu; mimo něj může tag vrátit NAK nebo nuly.
- Lokální fyzické ověření SRAM mapování ještě probíhá.
- Interval je přibližný; při pomalém RF se zpoždění zaznamená, bez dohánění.

### Hypotéza

Elektronika štítku může při RF aktivitě měnit session registry a v aktivním
okně (`NC_REG≈0x7C`) používat pass-through / SRAM. Jde o **hypotézu**,
nikoli potvrzený fakt.

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

## Plán dalšího vývoje

1. fyzicky ověřit SRAM `FAST_READ F0–FF` na referenčním štítku;
2. offline analýza timeline (korelace session ↔ SRAM);
3. sjednotit legacy skripty jako tenké wrappery nad CLI;
4. později připojit ElaTool k rozhraní OpenVusion.

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
