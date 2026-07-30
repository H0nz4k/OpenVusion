#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${1:-/c/Users/Honzák/Desktop/POZNAMKY/Projekty/Vusion_gu140}"
ELATEC_DOCS_ZIP="${2:-}"
FORCE="${FORCE:-0}"

log()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mChyba: %s\033[0m\n' "$*" >&2; exit 1; }

write_file() {
    local path="$1"
    local content="$2"

    mkdir -p "$(dirname "$path")"

    if [[ -e "$path" && "$FORCE" != "1" ]]; then
        warn "Ponecháno beze změny: $path"
        return
    fi

    printf '%s\n' "$content" > "$path"
    ok "Vytvořeno: $path"
}

log "OpenVusion Research – inicializace repozitáře"
printf 'Cíl: %s\n\n' "$PROJECT_ROOT"

mkdir -p \
    "$PROJECT_ROOT/docs" \
    "$PROJECT_ROOT/captures/nfc" \
    "$PROJECT_ROOT/captures/subghz" \
    "$PROJECT_ROOT/captures/twn4" \
    "$PROJECT_ROOT/images" \
    "$PROJECT_ROOT/notes" \
    "$PROJECT_ROOT/references/elatec" \
    "$PROJECT_ROOT/tools"

read -r -d '' README_CONTENT <<'EOF' || true
# OpenVusion Research – VUSION 2.6 BWR GU140

Výzkumný repozitář zaměřený na dokumentaci a legální interoperabilitu elektronického
štítku **SES-imagotag / Vusion 2.6 BWR GU140**.

## Zkoumaný kus

| Položka | Hodnota |
|---|---|
| Výrobce | SES-imagotag |
| Označení | VUSION 2.6 BWR GU140 |
| Revize | R2.0 |
| Model | EDG2-0200-4 |
| ID na štítku | AA2CD0C9 |
| Napájení | 2× CR2450 |
| NFC čip | NXP NTAG I²C Plus 1K |
| NFC UID | `04 36 7F 5A 2D 72 80` |
| ATQA | `00 44` (Elatec zobrazuje `44 00`) |
| SAK | `00` |
| GET_VERSION | `00 04 04 05 02 02 13 03` |

## Cíle

1. Zdokumentovat hardware a rozhraní tagu.
2. Prozkoumat NFC komunikaci přes Flipper Zero a Elatec TWN4.
3. Určit RF parametry a protokol v pásmu 868 MHz.
4. Ověřit možnosti vlastního firmware nebo vlastní gateway.
5. Udržovat odděleně ověřená fakta, hypotézy a surové záznamy.

## Struktura

- `docs/` – ověřená technická dokumentace
- `captures/` – surové NFC, TWN4 a Sub-GHz záznamy
- `images/` – fotografie a screenshoty
- `notes/` – pracovní deník, hypotézy a TODO
- `references/` – dokumentace výrobců
- `tools/` – pomocné skripty a utility

## Bezpečnost

Dokud nebude paměťová mapa a význam registrů ověřený, provádíme pouze čtení.
Do NFC EEPROM, session registrů ani firmware tagu nezapisujeme.
EOF

read -r -d '' HARDWARE_CONTENT <<'EOF' || true
# 01 – Hardware

## Identifikace zařízení

- Výrobce: SES-imagotag
- Typ: VUSION 2.6 BWR GU140
- Revize: R2.0
- Model: EDG2-0200-4
- ID na zadním štítku: AA2CD0C9
- Displej: černo-bílo-červený e-paper, úhlopříčka 2,6"
- Napájení: 2× CR2450

## Pozorované prvky

Na přední straně je průhledné optické okénko. Jeho funkce zatím není potvrzena.
Může obsahovat LED, fotodiodu, optický senzor nebo kombinaci více prvků.

## Stav rozebrání

Zadní kryt bateriového prostoru je otevřený, baterie zatím nebyly vyjmuty,
aby se zachoval aktuální stav zařízení.

## TODO

- [ ] Pořídit ostré fotografie PCB z obou stran
- [ ] Identifikovat MCU/radio SoC
- [ ] Identifikovat e-paper řadič
- [ ] Zmapovat testpointy
- [ ] Ověřit funkci optického okénka
- [ ] Zjistit zapojení baterií
EOF

read -r -d '' NFC_CONTENT <<'EOF' || true
# 02 – NFC

## Identifikace

Flipper Zero identifikoval zařízení jako:

- Device type: NTAG/Ultralight
- Typ: NTAG I²C Plus 1K
- UID: `04 36 7F 5A 2D 72 80`
- ATQA: `00 44`
- SAK: `00`
- Mifare/GET_VERSION: `00 04 04 05 02 02 13 03`
- Celkový počet stránek podle Flipperu: 236
- Spolehlivě načtené stránky: 2

## Originality signature

```text
81 4F D1 7F 22 AF 20 A7
3B 49 00 D3 72 6D 60 34
CA 5B 31 34 45 31 14 24
C1 87 B0 9F 11 03 B2 DD
```

## Pozorování

- Flipper tag načte okamžitě a opakovaně.
- Jeden testovaný telefon tag ani jiné NFC čipy nenačetl; pravděpodobná závada
  nebo konfigurace NFC v telefonu.
- Elatec TWN4 UID načítá spolehlivě.
- Zápis je zatím zakázán; neznáme význam aplikační paměti ani session registrů.

## TODO

- [ ] Ověřit GET_VERSION přes TWN4 transparentní přenos
- [ ] Přečíst stránky 0–15 standardním READ
- [ ] Zjistit stav ochrany heslem
- [ ] Zmapovat EEPROM, SRAM a session registry
- [ ] Ověřit, zda RF field detekce probouzí hlavní MCU
EOF

read -r -d '' RF_CONTENT <<'EOF' || true
# 03 – RF / Sub-GHz

## Pracovní hypotézy

- Evropská varianta pravděpodobně komunikuje v pásmu 868 MHz.
- Kandidátní frekvence: 868,35 MHz.
- Přesná modulace, datový tok, šířka kanálu a protokol zatím nejsou ověřené.
- Pro první pasivní měření bude použit Flipper Zero, případně externí CC1101.
- Později je vhodné použít SDR pro analýzu spektra a demodulaci.

## Zásady měření

- Pouze pasivní příjem v cizí infrastruktuře.
- Nevysílat do systému provozovny.
- Uchovávat původní RAW soubory beze změn.
- Ke každému záznamu uvést datum, místo, nastavení a použitou anténu.

## TODO

- [ ] Najít CC1101
- [ ] Ověřit, zda je modul pro 868/915 MHz
- [ ] Změřit aktivní kanály
- [ ] Určit modulaci
- [ ] Zachytit několik opakujících se rámců
- [ ] Porovnat čas RF rámců s případným blikáním LED
EOF

read -r -d '' FLIPPER_CONTENT <<'EOF' || true
# 04 – Flipper Zero

## NFC

Flipper Zero načetl NTAG I²C Plus 1K a vytvořil soubor `Vusion_tag.nfc`.

Doporučené uložení:

```text
captures/nfc/Vusion_tag.nfc
```

## Sub-GHz

Plánované použití:

- Frequency Analyzer pro orientační nalezení kanálu
- Read RAW pro pasivní záznam
- externí CC1101 pro lepší anténu a citlivost

## CC1101 – předběžné zapojení

> Před připojením ověřit pinout konkrétního modulu a používat pouze 3,3 V.

| CC1101 | Flipper Zero |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SCK | PB3 |
| MISO/SO | PA6 |
| MOSI/SI | PA7 |
| CSN | PA4 |
| GDO0 | PB2 |

## TODO

- [ ] Doplnit přesnou verzi firmware Flipperu
- [ ] Zdokumentovat polohu NFC antény vůči tagu
- [ ] Uložit původní `.nfc` dump
- [ ] Ověřit externí CC1101
EOF

read -r -d '' TWN4_CONTENT <<'EOF' || true
# 05 – Elatec TWN4

## Software

- ELATEC Director V5.07
- Připojení: USB / COM13
- Reader spolehlivě detekuje UID `04367F5A2D7280`
- Typ zobrazený Directorem: ISO14443A/MIFARE, 56 bit

## Naměřené hodnoty

### ISO14443A_GetATQA

```text
Request:  12 04
Response: 00 01 44 00
ATQA:     44 00
Result:   true
```

Poznámka: Flipper zapisuje ATQA jako `00 44`; rozdíl je v pořadí bajtů zobrazeném
jednotlivými nástroji.

### ISO14443A_GetSAK

```text
Request:  12 05
Response: 00 01 00
SAK:      00
Result:   true
```

### ISO14443A_SelectTag

```text
UID:      04 36 7F 5A 2D 72 80
Request:  12 09 01 52
Response: 00 00
Result:   fail
```

Funkce `SearchTag` přitom UID opakovaně detekuje. Selhání `SelectTag` může být
způsobeno očekávaným formátem parametru, stavem RF pole nebo způsobem práce
Directoru; zatím nejde o důkaz problému tagu.

### První pokus ISO14443_3_TDX

```text
TX zadané v UI: 1A 00 41 76
Request:         12 07 04 1A 00 41 76 FF FF 00
Response:        00 01 01 00
RX:              00
Result:          true
```

Tento pokus nepotvrzuje správný raw příkaz pro NTAG. Nejdříve je nutné ověřit
význam parametrů `ISO14443_3_TDX` v TWN4 API Reference.

## Relevantní dokumentace

Po rozbalení `Docs.zip` hledej zejména:

- `TWN4 API Reference DocRev31.pdf`
- `TWN4 Director User Guide DocRev17.pdf`
- `TWN4 Simple Protocol DocRev26.pdf`
- dokument konkrétního modelu TWN4

## TODO

- [ ] Najít dokumentaci funkce `ISO14443_3_TDX`
- [ ] Ověřit význam všech parametrů TDX
- [ ] Zjistit nutnost předchozí aktivace/selectu tagu
- [ ] Poslat bezpečný příkaz GET_VERSION `60`
- [ ] Poslat READ `30 00`
- [ ] Ukládat všechny Request/Response dvojice
EOF

read -r -d '' FIRMWARE_CONTENT <<'EOF' || true
# 06 – Firmware

Tato část zatím není prozkoumaná.

## Cíle

- identifikovat hlavní MCU/radio SoC,
- najít debug rozhraní,
- zjistit, zda je firmware chráněný proti čtení,
- zdokumentovat boot proces,
- až poté vyhodnotit možnost vlastního firmware.

## Zásada

Do firmware ani konfigurační flash se nezapisuje, dokud nebude existovat
obnovitelná záloha a ověřený programovací postup.
EOF

read -r -d '' GATEWAY_CONTENT <<'EOF' || true
# 07 – Gateway

Budoucí cíl: vlastní výzkumná gateway pro legálně vlastněné tagy.

Možné platformy:

- ESP32 + vhodný Sub-GHz transceiver,
- Raspberry Pi + CC1101/SDR,
- Flipper Zero jako přenosný diagnostický nástroj.

## Požadované funkce

- pasivní monitoring,
- dekódování rámců,
- evidence tagů,
- tvorba a přenos obrázků,
- REST/MQTT rozhraní,
- auditní log všech operací.
EOF

read -r -d '' LOG_CONTENT <<'EOF' || true
# Research log

## 2026-07-30

- Identifikován tag SES-imagotag VUSION 2.6 BWR GU140 R2.0.
- Zadní štítek uvádí model EDG2-0200-4 a ID AA2CD0C9.
- Napájení tvoří dvě baterie CR2450.
- Flipper Zero načetl NTAG I²C Plus 1K:
  - UID `04 36 7F 5A 2D 72 80`
  - ATQA `00 44`
  - SAK `00`
  - GET_VERSION `00 04 04 05 02 02 13 03`
- Elatec TWN4 potvrdil UID, ATQA a SAK.
- `ISO14443A_SelectTag` v Directoru selhal; příčina zatím neznámá.
- První TDX test neposlal ověřený NTAG příkaz.
- Založen repozitář `H0nz4k/Vusion_gu140`.
EOF

read -r -d '' HYPOTHESES_CONTENT <<'EOF' || true
# Hypotézy

> Tento dokument obsahuje neověřené domněnky. Nepřebírat je do `docs/` jako fakta,
> dokud nebudou potvrzeny měřením nebo primárním zdrojem.

- RF kanál může být kolem 868,35 MHz.
- Rádio pravděpodobně používá FSK/GFSK, ale není to potvrzené.
- Průhledný prvek vpředu může kombinovat LED a optický senzor.
- NFC čip může sloužit k identifikaci, servisu, probouzení nebo výměně dat s MCU
  přes I²C/SRAM.
- Cizí tag nemusí reagovat na adresované rámce jiné instalace, ale může přijímat
  broadcast/beacon rámce.
EOF

read -r -d '' TODO_CONTENT <<'EOF' || true
# TODO

## Nejbližší kroky

- [ ] Prohledat dokument `TWN4 API Reference DocRev31.pdf` pro `ISO14443_3_TDX`
- [ ] Zjistit přesný model Elatec TWN4
- [ ] Zopakovat SelectTag podle dokumentace
- [ ] Ověřit raw GET_VERSION a READ bez zápisu
- [ ] Najít CC1101 a pořídit fotografie modulu
- [ ] Přesunout `Vusion_tag.nfc` do `captures/nfc/`
- [ ] Uložit screenshoty Directoru do `images/`
- [ ] Doplnit licenci repozitáře
EOF

read -r -d '' GITIGNORE_CONTENT <<'EOF' || true
# Lokální a dočasné soubory
*.tmp
*.bak
*.log
Thumbs.db
.DS_Store

# Velké nebo citlivé pracovní výstupy
captures/**/working/
references/elatec/extracted-temp/

# IDE
.vscode/
.idea/
EOF

write_file "$PROJECT_ROOT/README.md" "$README_CONTENT"
write_file "$PROJECT_ROOT/.gitignore" "$GITIGNORE_CONTENT"
write_file "$PROJECT_ROOT/docs/01-hardware.md" "$HARDWARE_CONTENT"
write_file "$PROJECT_ROOT/docs/02-nfc.md" "$NFC_CONTENT"
write_file "$PROJECT_ROOT/docs/03-rf.md" "$RF_CONTENT"
write_file "$PROJECT_ROOT/docs/04-flipper.md" "$FLIPPER_CONTENT"
write_file "$PROJECT_ROOT/docs/05-twn4.md" "$TWN4_CONTENT"
write_file "$PROJECT_ROOT/docs/06-firmware.md" "$FIRMWARE_CONTENT"
write_file "$PROJECT_ROOT/docs/07-gateway.md" "$GATEWAY_CONTENT"
write_file "$PROJECT_ROOT/notes/research-log.md" "$LOG_CONTENT"
write_file "$PROJECT_ROOT/notes/hypotheses.md" "$HYPOTHESES_CONTENT"
write_file "$PROJECT_ROOT/notes/todo.md" "$TODO_CONTENT"

for empty_dir in \
    "$PROJECT_ROOT/captures/nfc" \
    "$PROJECT_ROOT/captures/subghz" \
    "$PROJECT_ROOT/captures/twn4" \
    "$PROJECT_ROOT/images" \
    "$PROJECT_ROOT/tools"
do
    write_file "$empty_dir/.gitkeep" ""
done

if [[ -n "$ELATEC_DOCS_ZIP" ]]; then
    [[ -f "$ELATEC_DOCS_ZIP" ]] || die "Docs.zip nebyl nalezen: $ELATEC_DOCS_ZIP"
    command -v unzip >/dev/null 2>&1 || die "Chybí příkaz unzip."

    log "Rozbaluji dokumentaci Elatec..."
    unzip -o "$ELATEC_DOCS_ZIP" -d "$PROJECT_ROOT/references/elatec"

    if [[ -d "$PROJECT_ROOT/references/elatec/Docs" ]]; then
        shopt -s dotglob nullglob
        mv "$PROJECT_ROOT/references/elatec/Docs/"* "$PROJECT_ROOT/references/elatec/" 2>/dev/null || true
        rmdir "$PROJECT_ROOT/references/elatec/Docs" 2>/dev/null || true
        shopt -u dotglob nullglob
    fi

    ok "Dokumentace Elatec byla rozbalena."
else
    warn "Docs.zip nebyl zadán; dokumentace Elatec se nerozbalovala."
fi

printf '\n'
ok "Hotovo."
printf '\nDoporučené další příkazy:\n'
printf '  cd "%s"\n' "$PROJECT_ROOT"
printf '  git status\n'
printf '  git add .\n'
printf '  git commit -m "Initialize OpenVusion Research structure"\n'
printf '  git push origin main\n'
