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
- příprava na sledování SRAM a společný NFC Logic Analyzer.

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
│       └── ...
├── tests/
├── docs/
├── scripts/
├── captures/
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

## Samostatné diagnostické nástroje

Některé výzkumné funkce zatím zůstávají jako samostatné Python skripty
v kořeni ElaToolu.

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

1. sjednotit jednorázové skripty pod jedno CLI;
2. implementovat read-only monitor 64B SRAM;
3. spojit session registry a SRAM do společné časové osy;
4. přidat sledování kritických EEPROM stránek `0x30–0x37`;
5. vytvořit NFC Logic Analyzer s exportem CSV, JSON a TXT;
6. později připojit ElaTool k rozhraní OpenVusion.

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
