# OpenVusion Research

OpenVusion je výzkumný projekt zaměřený na **read-only analýzu elektronických cenovek (ESL)**, jejich NFC rozhraní, lokální diagnostiku a rádiovou komunikaci.

Projekt vznikl postupným reverse engineeringem několika fyzických ESL platforem. Cílem není emulovat produkční backend ani aktivně zasahovat do cizí infrastruktury, ale **co nejlépe zdokumentovat hardware, protokoly, paměť, servisní rozhraní a chování tagů** z vlastních nebo oprávněně testovaných zařízení.

## Aktuální stav

Výzkum se nyní dělí do tří hlavních větví:

1. **NFC / ELATEC TWN4** — identifikace tagů, čtení paměti, registrů a session dat.
2. **Headless field capture — HWSniff v2** — Raspberry Pi Zero 2 W + TWN4 + fyzická tlačítka/DIP/LED.
3. **2.4 GHz RF research** — pasivní analýza rádiové komunikace různých ESL rodin.

---

# 1. ElaTool — NFC diagnostika a analýza

Součástí repozitáře je modul [`tools/ElaTool/`](tools/ElaTool/).

ElaTool slouží pro komunikaci přes NFC čtečku **ELATEC TWN4** a pro read-only analýzu ESL/tagů.

Aktuálně je fyzicky ověřena kompletní capture pipeline pro tag s **NTAG I²C Plus 1K**:

- detekce tagu a načtení UID;
- UID confirmation;
- NTAG `GET_VERSION`;
- identifikace varianty;
- kompletní EEPROM dump;
- `READ` / `FAST_READ`;
- NDEF a application data;
- konfigurační registry;
- session registry;
- verification;
- raw trace;
- export a persistence;
- porovnávání dumpů.

Referenční fyzický capture:

```text
UID:        04367F5A2D7280
Tag type:   0x80
UID length: 56 bit
GET_VERSION: 00 04 04 05 02 02 13 03
Identified: NTAG I2C Plus 1K
```

Kompletní EEPROM capture tohoto tagu obsahoval 226 pages a proběhl úspěšně.

Podrobnosti:

- [`tools/ElaTool/README.md`](tools/ElaTool/README.md)
- [`tools/HWSniff/docs/TAG_TECHNOLOGIES.md`](tools/HWSniff/docs/TAG_TECHNOLOGIES.md)

---

# 2. HWSniff v2 — terénní read-only appliance

[`tools/HWSniff/`](tools/HWSniff/) je malý headless sběrač pro **Raspberry Pi Zero 2 W**.

Aktuální v2 hardware:

- Raspberry Pi Zero 2 W;
- ELATEC TWN4 přes UART;
- 2 tlačítka;
- 2 DIP přepínače;
- 4 stavové LED;
- bez LCD a bez X11;
- offline capture na lokální storage.

HWSniff používá stejný shared `readonly_capture` engine jako PCSniff/ElaTool — nevznikla druhá nezávislá implementace TWN4 protokolu.

## V2 GPIO mapa

| Funkce | Physical pin | BCM GPIO |
|---|---:|---:|
| START | 40 | GPIO21 |
| STOP | 31 | GPIO6 |
| DIP1 | 32 | GPIO12 |
| DIP2 | 33 | GPIO13 |
| GREEN | 35 | GPIO19 |
| YELLOW | 36 | GPIO16 |
| RED | 37 | GPIO26 |
| BLUE | 38 | GPIO20 |

### Režimy

```text
DIP1 OFF + DIP2 OFF -> MAIN
DIP1 ON  + DIP2 OFF -> SWEETP
DIP1 OFF + DIP2 ON  -> plánovaný UPLOAD / Wi-Fi mode
DIP1 ON  + DIP2 ON  -> invalid / ERROR3
```

### MAIN workflow

```text
READY
  ↓ START
POSITIONING
  ↓ START při dostatečné kvalitě
READ
  ↓
READ_COMPLETE
  ↓
SAVE
  ↓
READY
```

Během READ fungují GREEN/YELLOW/RED jako šestikrokový progress bar:

```text
1/6 UID confirm      -> GREEN blink
2/6 identification  -> GREEN solid
3/6 EEPROM           -> GREEN + YELLOW blink
4/6 application      -> GREEN + YELLOW solid
5/6 session          -> + RED blink
6/6 verification     -> GREEN + YELLOW + RED solid
```

Po dokončení reader části bliknou všechny tři LED 5× a následuje SAVE.

Podrobnosti:

- [`tools/HWSniff/README.md`](tools/HWSniff/README.md)
- [`tools/HWSniff/docs/HARDWARE_V2.md`](tools/HWSniff/docs/HARDWARE_V2.md)
- [`tools/HWSniff/docs/SWEETP.md`](tools/HWSniff/docs/SWEETP.md)

---

# 3. SweetP — positioning / quality metric

SweetP není RF RSSI.

Jde o odvozenou metriku kvality komunikace založenou na úspěšnosti čtení, latenci, UID consistency a stabilitě.

Aktuální praktická pásma:

| Score | Stav |
|---:|---|
| 75–100 | GREEN — dobrá / ideální poloha |
| 56–74 | YELLOW — použitelná poloha |
| 40–55 | YELLOW / RED — hraniční oblast |
| 0–39 | RED — nevyhovující |

READ je aktuálně povolen od score `>= 56`.

---

# 4. Potvrzený teardown — VUSION 2.6 BWR GU140

Referenční SES-imagotag/VUSION tag byl po úspěšném NFC capture fyzicky rozebrán.

Na PCB byly potvrzeny zejména:

```text
Family:       VUSION 2.6 BWR GU140
PCB marking:  imagotag RFRTx024E
Main MCU/RF:  Texas Instruments CC2510F32
NFC:          NTAG I2C Plus 1K — fyzicky ověřeno capturem
Display:      e-paper
```

## Důležitý závěr

Tag je potřeba chápat jako zařízení s minimálně dvěma oddělenými komunikačními cestami:

```text
NFC / service / memory
        +
proprietary 2.4 GHz RF
```

`CC2510F32` potvrzuje proprietární 2.4GHz RF subsystém. Tento konkrétní RF čip **není nativní IEEE 802.15.4 rádio**, takže běžný 802.15.4 sniffer nemusí být pro tuto rodinu správný nástroj.

Na PCB byly nalezeny také servisní/testovací pady. Aktuální pracovní hypotéza je, že pět spodních padů odpovídá CC2510 debug rozhraní:

```text
VDD
GND
RESET_N
P2_1 / Debug Data
P2_2 / Debug Clock
```

Pro další výzkum je připraven low-cost **CC Debugger compatible** hardware. První kroky mají být pouze read-only:

```text
CHIP_ID
→ status / lock state
→ případné bezpečné čtení
```

Žádné erase/program operace nejsou součástí základního průzkumu.

Další HW detaily a úroveň jistoty jednotlivých závěrů jsou průběžně zapisovány v:

[`tools/HWSniff/docs/TAG_TECHNOLOGIES.md`](tools/HWSniff/docs/TAG_TECHNOLOGIES.md)

---

# 5. SOLUM ESL — druhá nalezená technologie

Při terénním testu byla nalezena další rodina ESL:

```text
Manufacturer: SOLUM
Model:        EL026F3BYA
FCC ID:       2AFWN-EL026F3WRA
```

TWN4 tyto tagy detekuje, ale nechovají se jako NTAG Type 2 / NTAG I²C.

Dva zaznamenané příklady:

```text
02FE422D65035909
02FE422D7723EF1B
```

Společné vlastnosti:

- `tag_type = 0x85`;
- 64bit identifier;
- UID confirmation funguje;
- NTAG `0x60 GET_VERSION` nedává očekávanou odpověď;
- Type-2 `0x30 READ` nedává očekávanou odpověď.

Aktuální silná pracovní hypotéza pro NFC větev je **FeliCa / NFC Forum Type 3**, ale tato klasifikace ještě není protokolově potvrzena. Proto kód nesmí natvrdo mapovat `0x85 == FeliCa` bez dalšího ověření.

## RF větev SOLUM

Pro tuto rodinu je současný výzkumný směr proprietary 2.4GHz/GFSK provoz. Praktickým kandidátem pro experimentální pasivní activity logger je **Seeed XIAO nRF52840**, který již máme k dispozici.

První cíl není aktivní komunikace ani emulace tagu, ale pouze pasivní mapování:

```text
čas
frekvence / kanál
RSSI / aktivita
periodicita
případný hopping pattern
```

Teprve následně má smysl řešit packet framing a dekódování.

---

# 6. Architektura výzkumu

Aktuální model projektu:

```text
                         OpenVusion
                             |
        +--------------------+--------------------+
        |                    |                    |
        v                    v                    v
     ElaTool              HWSniff              RF research
        |                    |                    |
        |                    |                    +-- VUSION / CC2510
        |                    |                    +-- SOLUM / 2.4 GHz
        |                    |
        +------ shared readonly_capture ----------+
```

Zásada projektu je **sdílet ověřenou reader/capture logiku** a nevytvářet paralelní protokolové implementace bez důvodu.

---

# 7. Výzkumné zásady

Projekt je veden jako diagnostický a výzkumný projekt.

Preferujeme:

- read-only operace;
- pasivní RF capture;
- dokumentování raw dat;
- oddělení `confirmed` / `inferred` / `hypothesis`;
- reprodukovatelné fyzické testy;
- zachování originálních dumpů;
- testování pouze na vlastním hardware nebo tam, kde je k testu souhlas.

U každého nového tagu se mají zaznamenat:

- výrobce/model;
- UID/ID a jeho délka;
- reader-reported tag type;
- raw commands/responses;
- co bylo fyzicky potvrzeno;
- co je pouze pracovní hypotéza;
- PCB marking a IC part numbers, pokud je k dispozici teardown;
- další bezpečné read-only kroky.

---

# 8. Struktura repozitáře

```text
OpenVusion/
├── tools/
│   ├── ElaTool/        # NFC reader/capture/analyza
│   └── HWSniff/        # headless field appliance
├── captures/           # capture data / vzorky
├── docs/               # obecná dokumentace
├── elatec/             # ELATEC poznámky/data
├── images/             # fotografie / obrázky
├── notes/              # výzkumné poznámky
├── Vusion_tag.nfc      # referenční NFC data
└── README.md
```

---

# 9. Další plán

Nejbližší výzkumné kroky:

### VUSION / CC2510

- zmapovat debug pady;
- připojit CC Debugger compatible interface;
- přečíst CHIP_ID a debug status;
- zjistit případný lock state;
- pokud je bezpečně možné, analyzovat firmware/data bez mazání či programování;
- pasivně zkoumat proprietary 2.4 GHz komunikaci.

### SOLUM

- doplnit FeliCa/Type-3 read-only probe do ElaTool/HWSniff;
- potvrdit nebo vyvrátit mapování `tag_type 0x85`;
- připravit XIAO nRF52840 jako pasivní 2.4GHz activity logger;
- mapovat aktivní kanály a časovou strukturu RF provozu.

### HWSniff

- dokončit fyzickou validaci v2 na Raspberry Pi Zero 2 W;
- zachovat deterministic state machine;
- doplnit DIP2 UPLOAD/Wi-Fi workflow;
- zachovat jeden START = jeden capture.

---

# 10. Dokumentace

Nejdůležitější dokumenty:

- [`tools/ElaTool/README.md`](tools/ElaTool/README.md)
- [`tools/HWSniff/README.md`](tools/HWSniff/README.md)
- [`tools/HWSniff/docs/HARDWARE_V2.md`](tools/HWSniff/docs/HARDWARE_V2.md)
- [`tools/HWSniff/docs/TAG_TECHNOLOGIES.md`](tools/HWSniff/docs/TAG_TECHNOLOGIES.md)
- [`tools/HWSniff/docs/SWEETP.md`](tools/HWSniff/docs/SWEETP.md)
- [`tools/HWSniff/docs/STORAGE_FORMAT.md`](tools/HWSniff/docs/STORAGE_FORMAT.md)

---

## Status

Projekt je aktivní výzkum. Některé části jsou fyzicky ověřené, jiné jsou explicitně vedené jako pracovní hypotézy. Dokumentace se průběžně aktualizuje podle dalších capture, teardownů a RF měření.
