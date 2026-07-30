# Changelog

Všechny významné změny projektu jsou zapisovány do tohoto souboru.
Formát vychází z [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
a verzování používá [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-25

### Added

- Automatický výběr jediné připojené čtečky ELATEC podle USB VID `09D8`.
- Záložní ověření portů pomocí Simple Protocol, když čtečku nelze poznat podle USB identifikace.
- Přepínač `--show-all-candidates` pro diagnostický výpis všech číselně shodných variant.
- Testy automatického výběru portu a zjednodušeného výstupu analýzy.
- Příkaz `test-medium`, který ověří Simple Protocol, načte kartu a vypíše typ média bez hledání DB kódu.
- Lokální databáze `data/samples.json`, která ukládá anonymizované otisky a kandidátní pravidla podle `TagType` a hledá společné pravidlo nad více kartami stejného typu.
- Příkaz `update-reader` jako bezpečná příprava pro PRS firmware a pozdější sestavení vlastního firmware.
- Jednotný spouštěcí soubor `elaUIDtool.bat`, který vytvoří prostředí, nainstaluje projekt a nabídne menu 1–3.

### Changed

- Ruční výběr portu se zobrazí pouze při více čtečkách nebo při nejednoznačné detekci.
- Výchozí výstup analýzy ukazuje pouze doporučené nastavení AppBlasteru.
- Pojem kandidát je ve výstupu vysvětlen jako číselně shodná varianta bitového výřezu.
- Alternativní varianty jsou ve výchozím režimu skryté, ale zůstávají uložené v JSON výsledku.
- Výchozí limit analyzovaných shod byl zvýšen na 50.
- Po úspěšné interaktivní analýze se vzorek automaticky přidá do lokální databáze a vypíše se počet společných pravidel pro daný typ média.
- Syrové UID a DB číslo se v databázi vzorků neukládají; používá se pouze SHA-256 otisk a seznam kandidátních pravidel.

### Maintenance

- Lokální adresář `files520/` a archiv `files520.zip` jsou ignorovány Gitem.
- Lokální adresář `data/` s naměřenými UID a DB kódy je ignorován Gitem.

## [0.1.3] - 2026-06-25

### Fixed

- Parser `SearchTag` nyní správně zpracovává délkový prefix typu `Byte Array(Var)`. Oprava zabraňuje tomu, aby byl počet bajtů zahrnut do UID a poslední bajt UID zahozen.
- Referenční odpověď `00014028053D00C000D4` se nyní dekóduje jako UID `3D00C000D4`.

### Changed

- README a GitHub dokumentace byly přizpůsobeny oficiálnímu repozitáři `H0nz4k/elaUIDtool`.

### Planned

- Hledání společného transformačního pravidla nad více kartami.
- Přesnější fingerprint médií pomocí ATQA, SAK, ATS a typově specifických příkazů.
- Automatický export projektu nebo firmware pro AppBlaster.
- Bezpečné automatické přepnutí čtečky na PRS firmware a návrat k produkčnímu firmware.
## [0.1.2] - 2026-06-25

### Added

- Git repozitář s historií verzí a anotovanými tagy.
- Pravidla Semantic Versioning a Conventional Commits.
- Automatický release helper `scripts/release.py`.
- Kontrola konzistence verze `scripts/check_version.py`.
- GitHub Actions testy pro Python 3.10 až 3.13.
- Architektonická dokumentace projektu.
- `.gitattributes` pro stabilní konce řádků na Windows a Linuxu.

### Changed

- Verze balíčku má jediný zdroj pravdy v `elatec_uid_tool.__version__`.
- README bylo sjednoceno s aktuálním stavem projektu.

## [0.1.1] - 2026-06-25

### Added

- Detekce pravděpodobného ELATEC portu podle USB VID `09D8`.
- Přehlednější výpis sériových portů.
- Příkaz `prepare-reader` pro nalezení PRS image v Developer Packu.
- Testy výběru portu a hledání firmware.

### Changed

- Interaktivní režim používá automatickou detekci formátu DB kódu.
- Port lze vybírat číslem položky a ELATEC port je nabízen jako výchozí.
- Chybová zpráva vysvětluje požadavek na PRS Simple Protocol firmware.

## [0.1.0] - 2026-06-25

### Added

- První terminálový analyzátor UID.
- Komunikace s ELATEC TWN4 pomocí Simple Protocol v ASCII režimu.
- Čtení modelu, podporovaných LF/HF typů, `TagType`, bitové délky a raw UID.
- Hledání bitového výřezu, Reverse Bit Order a Reverse Byte Order.
- Referenční test `3D00C000D4 -> 12583124`.
- Export výsledku do JSON.
