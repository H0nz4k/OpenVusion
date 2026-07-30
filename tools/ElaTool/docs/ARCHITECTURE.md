# Architektura

- `protocol.py`: komunikace s TWN4.
- `ports.py`: automatický výběr COM portu.
- `tagtypes.py`: popis typu média.
- `analyzer.py`: analýza bitového výřezu.
- `ntag.py`: read-only NTAG I²C Plus (GET_VERSION, READ, FAST_READ, session, SRAM).
- `capture/`: NFC Logic Analyzer (timeline session + SRAM).
- `samples.py`: anonymizovaná pravidla podle typu média.
- `commands.py`: uživatelské příkazy.
- `cli.py`: příkazové rozhraní včetně `logic-analyzer`.
- `elaUIDtool.bat`: instalace a menu pro Windows.

NFC diagnostika: viz [NFC_LOGIC_ANALYZER.md](NFC_LOGIC_ANALYZER.md).

Tok dat: médium → TWN4 → RAW UID → porovnání s DB ID → doporučené nastavení AppBlasteru.

Jedna rozpoznaná ELATEC čtečka se vybere automaticky. Více čteček nebo nejasná detekce vyvolá ruční výběr.

Lokální `data/samples.json` ukládá jen anonymizovaný otisk a kandidátní pravidla. Složka `files520/` je lokální a Git ji ignoruje.
