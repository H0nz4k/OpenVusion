# Architektura

- `protocol.py`: komunikace s TWN4.
- `ports.py`: automatický výběr COM portu.
- `tagtypes.py`: popis typu média.
- `analyzer.py`: analýza bitového výřezu.
- `samples.py`: anonymizovaná pravidla podle typu média.
- `commands.py`: uživatelské příkazy.
- `cli.py`: příkazové rozhraní.
- `elaUIDtool.bat`: instalace a menu pro Windows.

Tok dat: médium → TWN4 → RAW UID → porovnání s DB ID → doporučené nastavení AppBlasteru.

Jedna rozpoznaná ELATEC čtečka se vybere automaticky. Více čteček nebo nejasná detekce vyvolá ruční výběr.

Lokální `data/samples.json` ukládá jen anonymizovaný otisk a kandidátní pravidla. Složka `files520/` je lokální a Git ji ignoruje.
