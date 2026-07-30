[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\Users\Honzák\Desktop\POZNAMKY\Projekty\Vusion_gu140",
    [string]$ElatecDocsZip = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Utf8File {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if ((Test-Path -LiteralPath $Path) -and -not $Force) {
        Write-Host "Ponecháno beze změny: $Path" -ForegroundColor DarkYellow
        return
    }

    Set-Content -LiteralPath $Path -Value $Content -Encoding utf8
    Write-Host "Vytvořeno: $Path" -ForegroundColor Green
}

Write-Host ""
Write-Host "OpenVusion Research – inicializace repozitáře" -ForegroundColor Cyan
Write-Host "Cíl: $ProjectRoot"
Write-Host ""

# Základní adresářová struktura
$directories = @(
    "docs",
    "captures\nfc",
    "captures\subghz",
    "captures\twn4",
    "images",
    "notes",
    "references\elatec",
    "tools"
)

New-Item -ItemType Directory -Path $ProjectRoot -Force | Out-Null

foreach ($directory in $directories) {
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot $directory) -Force | Out-Null
}

$readme = @'
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
'@

$hardware = @'
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
'@

$nfc = @'
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
'@

$rf = @'
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
'@

$flipper = @'
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
'@

$twn4 = @'
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
'@

$firmware = @'
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
'@

$gateway = @'
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
'@

$log = @'
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
'@

$hypotheses = @'
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
'@

$todo = @'
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
'@

$gitignore = @'
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
'@

$keep = ""

Write-Utf8File -Path (Join-Path $ProjectRoot "README.md") -Content $readme
Write-Utf8File -Path (Join-Path $ProjectRoot ".gitignore") -Content $gitignore
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\01-hardware.md") -Content $hardware
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\02-nfc.md") -Content $nfc
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\03-rf.md") -Content $rf
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\04-flipper.md") -Content $flipper
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\05-twn4.md") -Content $twn4
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\06-firmware.md") -Content $firmware
Write-Utf8File -Path (Join-Path $ProjectRoot "docs\07-gateway.md") -Content $gateway
Write-Utf8File -Path (Join-Path $ProjectRoot "notes\research-log.md") -Content $log
Write-Utf8File -Path (Join-Path $ProjectRoot "notes\hypotheses.md") -Content $hypotheses
Write-Utf8File -Path (Join-Path $ProjectRoot "notes\todo.md") -Content $todo

# Git neukládá prázdné adresáře, proto v nich vytvoříme .gitkeep.
foreach ($emptyDirectory in @("captures\nfc", "captures\subghz", "captures\twn4", "images", "tools")) {
    Write-Utf8File -Path (Join-Path $ProjectRoot "$emptyDirectory\.gitkeep") -Content $keep
}

# Volitelné rozbalení dokumentace Elatec.
if ($ElatecDocsZip) {
    if (-not (Test-Path -LiteralPath $ElatecDocsZip)) {
        throw "Soubor Docs.zip nebyl nalezen: $ElatecDocsZip"
    }

    $destination = Join-Path $ProjectRoot "references\elatec"
    Write-Host ""
    Write-Host "Rozbaluji dokumentaci Elatec do: $destination" -ForegroundColor Cyan
    Expand-Archive -LiteralPath $ElatecDocsZip -DestinationPath $destination -Force

    # Pokud ZIP obsahuje nadbytečnou kořenovou složku Docs, obsah přesuneme o úroveň výše.
    $nestedDocs = Join-Path $destination "Docs"
    if (Test-Path -LiteralPath $nestedDocs) {
        Get-ChildItem -LiteralPath $nestedDocs -Force | ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
        Remove-Item -LiteralPath $nestedDocs -Recurse -Force
    }

    Write-Host "Dokumentace Elatec byla rozbalena." -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "Docs.zip nebyl zadán; dokumentace Elatec se nerozbalovala." -ForegroundColor DarkYellow
    Write-Host 'Použití: .\Initialize-OpenVusion.ps1 -ElatecDocsZip "C:\cesta\Docs.zip"'
}

Write-Host ""
Write-Host "Hotovo." -ForegroundColor Green
Write-Host ""
Write-Host "Doporučené další příkazy:" -ForegroundColor Cyan
Write-Host "  Set-Location `"$ProjectRoot`""
Write-Host "  git status"
Write-Host "  git add ."
Write-Host '  git commit -m "Initialize OpenVusion Research structure"'
Write-Host "  git push origin main"
Write-Host ""
