# VUSION / NTAG I²C Plus — živý SRAM mailbox stock firmwaru

Datum: 2026-08-07

Tento dokument navazuje na `VUSION_NTAG_SESSION_HANDSHAKE_2026-08-07.md` a shrnuje následné fyzické experimenty, při kterých byl zachycen skutečný 64bajtový obsah NTAG I²C Plus SRAM přesně v okamžiku, kdy stock MCU nastavilo `SRAM_RF_READY=1`.

## Testovaný kus

```text
Rodina:      SES-imagotag / VUSION 2.6
MCU/radio:   TI CC2510F32
NFC:         NTAG I2C Plus 1K
UID:         04367F5A2D7280
tag_type:    0x80
GET_VERSION: 00 04 04 05 02 02 13 03
Čtečka:      TWN4/B1.64/NCF5.20/PRS1.04
```

Dřívější EEPROM dump stejného fyzického tagu obsahuje:

```text
NDEF URL: https://nfc.imagotag.com/AA2CD0C9
SES ID:   AA2CD0C9
EEPROM:   C9 D0 2C AA   # little-endian kopie SES ID
```

Aplikační/manufacturer blok `0x30..0x37` obsahuje:

```text
A0 81 FF FF FF FF FF FF FF FF FF FF C9 D0 2C AA
FF 3A 10 00 00 33 00 02 01 0D 02 02 D5 01 6C 93
```

## Bezpečnostní hranice experimentu

Použitý výzkumný postup byl non-writing:

- žádný tag `WRITE`;
- žádný zápis konfiguračních/session registrů;
- žádné password/auth pokusy;
- žádná emulace;
- SRAM `F0..FF` se četla právě jednou na jeden detekovaný `SRAM_RF_READY` event.

Důležitá nuance: úplný RF-side read SRAM je sice ne-zápisová operace, ale **není behaviorálně pasivní**. Fyzicky jsme ověřili, že spotřebování celého RF bufferu posune NTAG pass-through handshake.

## Trigger pro zachycení

SRAM se četla pouze v tomto stavu:

```text
PTHRU_ON_OFF     = 1
TRANSFER_DIR     = I2C -> NFC
SRAM_RF_READY    = 1
RF_FIELD_PRESENT = 1
```

Bezprostředně před čtením bylo opakovaně naměřeno:

```text
Session: 7C 00 F8 48 08 01 29 00
NC_REG = 0x7C
NS_REG = 0x29
```

Dekódování:

```text
PTHRU_ON_OFF  = 1
TRANSFER_DIR  = I2C -> NFC
RF_LOCKED     = 1
SRAM_RF_READY = 1
FIELD_PRESENT = 1
```

## První přímý capture — 3 cykly

Ve třech samostatných RF cyklech byl kompletní 64B SRAM obsah získán 3/3.

### Cyklus 1

```text
C00101010000000000000000C9D02CAA
0D46F0C4932C9D2ADDDA99291D8AE5C8
1F4A36174CF647F0C7100F46B3F704C0
00000000000000000000000000001E62
```

SHA-256:

```text
6f21fc1083f1412433a21f5bd31c24ac7b8a9a38e84aa3e81621b38d92584ea6
```

### Cyklus 2

```text
C00101010000000000000000C9D02CAA
6EED0D4533577CE20845F3473017CC56
5E3992ACFEC1902F9EE94E7567E88DE5
0000000000000000000000000000DFC7
```

SHA-256:

```text
cbefd6ff6dd499b088f3f6817ab199a5448151e76003fd29810bbf64dde34786
```

### Cyklus 3

```text
C00101010000000000000000C9D02CAA
0986235BF9C2D0DF5A3A922C1E89A6FB
3A128CE64B75A7F8C1108F662B9D291E
00000000000000000000000000009FA8
```

SHA-256:

```text
1f50fb5b52879b1185b591dcbc580c01ddaffe21e9ebe64740455fc272d5761a
```

Už tři vzorky ukázaly velmi čisté členění:

```text
0x00..0x0F  konstantní
0x10..0x2F  dynamické
0x30..0x3D  konstantní nuly
0x3E..0x3F  dynamický trailer
```

## Stav po úplném SRAM readu

Po každém kompletním 64B readu se session stav změnil na:

```text
7D 00 F8 48 08 01 21 00
```

tedy:

```text
PTHRU_ON_OFF  = 1
TRANSFER_DIR  = NFC -> I2C
RF_LOCKED     = 1
SRAM_RF_READY = 0
FIELD_PRESENT = 1
```

To přímo potvrzuje:

```text
MCU připraví RF zprávu
-> I2C -> NFC
-> SRAM_RF_READY=1
-> NFC/RF strana přečte celý buffer
-> SRAM_RF_READY=0
-> TRANSFER_DIR se otočí na NFC -> I2C
```

Úplný read tedy funguje jako **consume/acknowledge** transientního mailboxu na úrovni NTAG pass-through state machine.

## Rozšířený test — 50 samostatných RF cyklů

Následně bylo provedeno 50 fresh RF-off/RF-on cyklů se stejným pravidlem: právě jeden SRAM read na jeden `READY` event.

Výsledek:

```text
úspěšné SRAM capture: 50 / 50
ztracené READY eventy: 0
změna UID: 0
chyby 64B readu: 0
```

### Čas do `SRAM_RF_READY`

```text
minimum:  0.474704 s
maximum:  0.554278 s
průměr:   0.480126 s
medián:   0.479664 s
```

Cyklus 8 byl jediný výrazný timing outlier:

```text
cycle 8 = 0.554278 s
```

Po jeho vynechání:

```text
minimum:  0.474704 s
maximum:  0.480648 s
průměr:   0.478613 s
σ:        2.075 ms
```

### Doba samotného čtení 64 B

```text
minimum:  20.824 ms
maximum:  22.262 ms
průměr:   21.354 ms
medián:   21.297 ms
σ:        0.290 ms
```

Mechanismus je tedy velmi časově reprodukovatelný.

## Definitivní 64B layout z 50 vzorků

Všech 50 payloadů odpovídá stejné masce:

```text
Offset        Stav           Hodnota / popis
-----------------------------------------------------------------
0x00–0x03     konstantní     C0 01 01 01
0x04–0x0B     konstantní     00 00 00 00 00 00 00 00
0x0C–0x0F     konstantní     C9 D0 2C AA
0x10–0x1F     dynamické      16 B
0x20–0x2F     dynamické      16 B
0x30–0x3D     konstantní     14 × 00
0x3E–0x3F     dynamické      2 B
```

Celkem:

```text
konstantní: 30 / 64 bajtů
dynamické:  34 / 64 bajtů
```

## Zásadní korelace SES ID

Pevná hlavička je:

```text
C0 01 01 01 00 00 00 00 00 00 00 00 C9 D0 2C AA
```

Poslední 4 bajty této hlavičky jsou:

```text
C9 D0 2C AA
```

Po otočení little-endian:

```text
AA 2C D0 C9
-> AA2CD0C9
```

To je přesně SES ID z NDEF URL stejného fyzického tagu.

Máme tedy přímou fyzickou vazbu:

```text
NDEF URL
  https://nfc.imagotag.com/AA2CD0C9
        |
        v
SES ID AA2CD0C9
        |
        v little-endian
C9 D0 2C AA
        |
        +-- EEPROM page 0x33
        +-- živý SRAM mailbox offset 0x0C
```

Toto je silný důkaz, že zachycený SRAM frame je skutečná strukturovaná zpráva stock VUSION firmwaru a obsahuje explicitní identitu zařízení.

## Dynamická oblast `0x10..0x2F`

Dynamická část má přesně 32 B a přirozeně se dělí na dvě 16B poloviny:

```text
0x10..0x1F  pole A
0x20..0x2F  pole B
```

Statistika z 50 vzorků:

```text
průměrná entropie offsetů 0x10..0x1F: 5.4598 bitu
průměrná entropie offsetů 0x20..0x2F: 5.4645 bitu
empirické maximum při 50 vzorcích:   5.6439 bitu
```

Na jednom dynamickém offsetu bylo typicky 42–49 různých hodnot z 50 vzorků.

Globální bitová rovnováha 34 dynamických bajtů na zprávu:

```text
6698 jedniček / 13600 bitů = 49.25 %
```

Byte-frequency chi-square test proti rovnoměrnému rozdělení:

```text
chi2 = 235.059
df   = 255
p    ~= 0.810
```

Pouhé histogramy tedy působí velmi náhodně.

## Dlouhé opakované sekvence — nejdůležitější statistický nález

Navzdory vysoké entropii se mezi různými RF cykly opakují přesné dlouhé substrings.

Výsledek sliding-window porovnání dynamické 32B oblasti:

| délka shody | počet oken | opakované skupiny | očekávané náhodné kolize* |
|---:|---:|---:|---:|
| 4 B  | 1450 | 57 | `2.446e-04` |
| 8 B  | 1250 | 27 | `4.232e-14` |
| 12 B | 1050 | 11 | `6.951e-24` |
| 14 B | 950  | 4  | `8.682e-29` |
| 16 B | 850  | 1  | `1.060e-33` |

\* Orientační očekávání pro nezávislé rovnoměrně náhodné bajty; overlapping windows a skutečná struktura frame tuto jednoduchou aproximaci neberou v úvahu. Čísla slouží jen jako měřítko, jak extrémně nepravděpodobné by dlouhé shody byly u nezávislého RNG.

### Přesná 16B shoda

```text
01 83 20 18 0A C5 10 CC 55 7C E1 0B 86 E0 88 66
```

byla nalezena jako:

```text
cycle 5,  block 2 / SRAM 0x20..0x2F
cycle 46, block 1 / SRAM 0x10..0x1F
```

Tedy celý 128bitový blok se opakoval v jiném cyklu a v jiné polovině dynamické oblasti.

Další reprezentativní shody:

```text
14 B: F5 87 A0 3B 51 FC 42 70 27 18 49 36 57 7C
      cycle 8 offset +0
      cycle 35 offset +2

13 B: 11 4C 36 97 6C AE 7D 21 18 C9 96 6F EE
      cycle 10 offset +0
      cycle 19 offset +19

12 B: EC 4E F5 87 A0 7B 61 A8 BD 31 14 0C
      cycle 13 offset +4
      cycle 34 offset +0
```

## Interpretace dynamických dat

50 vzorků už vylučuje jednoduchou představu, že jde o 32 zcela nezávislých čerstvě náhodných bajtů v každém RF cyklu.

Nejlépe odpovídají třídy hypotéz:

1. deterministický pseudonáhodný generátor se stavem;
2. keystream / lookup sekvence / kruhový buffer, ze kterého se vybírají různá okna;
3. deterministicky odvozený challenge materiál;
4. kombinace více polí generovaných stejným mechanismem.

To **není** důkaz konkrétní kryptografie a neznamená to, že je autentizační mechanismus prolomen. Potvrzen je pouze silný deterministický vztah mezi některými dynamickými bajty napříč cykly.

## Hammingova vzdálenost

Pro dynamických 34 B (`0x10..0x2F` + trailer `0x3E..0x3F`) je mezi všemi dvojicemi 50 cyklů:

```text
průměr: 136.251 bitu z 272
minimum: 88 bitů
maximum: 160 bitů
```

Pro dvě nezávislé náhodné 272bitové hodnoty je očekávaný průměr 136 bitů.

Nejnižší pozorovaná vzdálenost:

```text
cycle 24 <-> cycle 44 = 88 bitů
```

Globálně tedy data vypadají velmi dobře promíchaně, zatímco lokálně obsahují velmi dlouhé přesné shody. To opět podporuje model deterministického streamu/stavového generátoru spíše než prostého counteru nebo statických polí.

## Čítače a checksumy

Automatická kontrola všech možných offsetů pro:

```text
uint16 LE
uint16 BE
uint32 LE
uint32 BE
```

nenašla jednoduchý monotónní counter ani konstantní deltu.

Pro trailer `0x3E..0x3F` byly testovány běžné kandidáty:

```text
sum16
Fletcher-16
CRC-16/ARC
CRC-16/MODBUS
CRC-16/CCITT-FALSE
CRC-16/X25
```

na několika přirozených rozsazích frame.

Výsledek:

```text
žádná univerzální shoda
```

Všech 50 kompletních 16bitových trailerů bylo unikátních.

Proto trailer zatím označujeme pouze jako:

```text
dynamický 16bit trailer
```

nikoli jako CRC.

## Korelace s časováním

Nebyla nalezena žádná silná lineární korelace (`|Pearson r| >= 0.80`) mezi jednoduchými 1/2/4bajtovými poli a:

- časem do `READY`;
- latencí samotného 64B readu.

To opět nepodporuje jednoduchý timestamp/counter model.

## Reprodukovaný stavový automat — 50 cyklů

Při přibližně 10ms vzorkování session registrů byly pozorovány tyto komprimované cesty:

### 37 / 50 cyklů

```text
19 00 F8 48 08 01 01 00
-> 7C 00 F8 48 08 01 41 00
-> 7C 00 F8 48 08 01 29 00
```

### 11 / 50 cyklů

```text
19 00 F8 48 08 01 01 00
-> 7C 00 F8 48 08 01 29 00
```

### 2 / 50 cyklů

```text
19 00 F8 48 08 01 01 00
-> 19 00 F8 48 08 01 41 00
-> 7C 00 F8 48 08 01 29 00
```

Mezistav `NS_REG=0x41` znamená:

```text
I2C_LOCKED=1
RF_FIELD_PRESENT=1
```

Následující `NS_REG=0x29` znamená:

```text
RF_LOCKED=1
SRAM_RF_READY=1
RF_FIELD_PRESENT=1
```

Pokud se `0x41` v některém cyklu neobjevil ve vzorcích, není tím prokázáno, že fyzicky nenastal — mohl proběhnout mezi dvěma ~10ms vzorky.

Po úplném SRAM readu bylo 50/50:

```text
7D 00 F8 48 08 01 21 00
```

To dává velmi konzistentní pracovní state machine:

```text
idle / persistent NC=0x19
-> MCU získá I2C stranu
-> zapne pass-through + I2C->NFC
-> naplní SRAM
-> RF_LOCKED + SRAM_RF_READY
-> reader spotřebuje 64B mailbox
-> SRAM_RF_READY se zruší
-> směr se otočí NFC->I2C
```

## Pracovní layout frame

```text
64B SRAM message
|
+-- 0x00..0x03  C0 01 01 01
|               pravděpodobně protocol/command header
|
+-- 0x04..0x0B  8 x 00
|               rezervované / parametry
|
+-- 0x0C..0x0F  C9 D0 2C AA
|               SES ID AA2CD0C9, little-endian
|
+-- 0x10..0x1F  dynamické pole A, 16 B
|
+-- 0x20..0x2F  dynamické pole B, 16 B
|
+-- 0x30..0x3D  14 x 00
|               rezervované / padding
|
+-- 0x3E..0x3F  dynamický 16bit trailer
```

## Úroveň jistoty

### Fyzicky potvrzeno

- stock CC2510 reaguje na NFC pole a aktivuje NTAG pass-through;
- `SRAM_RF_READY=1` spolehlivě označuje 64B MCU->NFC mailbox;
- 50/50 full SRAM readů bylo úspěšných;
- frame má vždy stejné konstantní/dynamické rozložení;
- `C9 D0 2C AA` je v každém frame na offsetu `0x0C`;
- tato hodnota je little-endian SES ID `AA2CD0C9`, které je současně v NDEF a EEPROM;
- po úplném readu se vždy zruší `SRAM_RF_READY` a otočí `TRANSFER_DIR`;
- dvě 16B dynamické poloviny obsahují dlouhé přesně se opakující sekvence napříč cykly;
- alespoň jednou se celý 16B blok objevil v jiné pozici jiného RF cyklu;
- jednoduchý 16/32bit counter nebyl nalezen;
- testované běžné CRC16 neodpovídají traileru;
- trailer měl 50/50 unikátních hodnot.

### Silná inference

- `C0 01 01 01` obsahuje typ/verzi/flags nebo jiné protocol metadata;
- `0x10..0x2F` je generováno deterministickým stavovým/pseudonáhodným mechanismem;
- obě 16B poloviny pravděpodobně používají stejný zdroj nebo stejný formát;
- úplný RF read je acknowledgement/consume krok stock mailbox protokolu.

### Zatím nepotvrzeno

- že pole A je challenge;
- že pole B je response;
- že je použit AES nebo jiný konkrétní algoritmus;
- že trailer je MAC, CRC, PRNG state nebo session ID;
- přesný význam `C0 01 01 01`;
- přesný stock SES MCU<->NFC aplikační protokol.

## Srovnání s veřejným reverse engineeringem

### fanhuanji/VUSION4.2BWR_GL340

Veřejný projekt pro jiný VUSION model používá rovněž CC2510 a NTAG-I2C-like pass-through mechanismus. Jeho zdrojový kód pracuje s:

```text
SDA = P0_4
SCL = P0_6
I2C NFC address = 0xAA / 0xAB
session NC/NS registry
PTHRU_ON_OFF
TRANSFER_DIR
SRAM ready bity
4 x 16B SRAM bloky
```

Projekt má vlastní custom MCU firmware a vlastní aplikační handshake. Je tedy relevantní jako nezávislé potvrzení **hardwarového mechanismu**, ne jako důkaz významu stock SES payloadu.

Reference:

- https://github.com/fanhuanji/VUSION4.2BWR_GL340
- `src/nfc/i2c.h`
- `src/nfc/i2c.c`
- `src/main.c`

### BeatSkip/SES-Imagotag-UU340

Tento projekt je důležitý hlavně pro variantovou taxonomii. Popisuje jinou VUSION 2.6/2.2 variantu:

```text
MCU/radio: AX8052F143
NFC:       FM11NT081DS
```

Náš fyzický kus má naproti tomu:

```text
MCU/radio: CC2510F32
NFC:       NTAG I2C Plus 1K
```

Proto nelze automaticky přenášet pinout, firmware nebo NFC protokol mezi různými VUSION 2.6 kusy jen podle vzhledu/modelové řady.

Reference:

- https://github.com/BeatSkip/SES-Imagotag-UU340

## Doporučený další krok

Nejvyšší informační hodnotu má nyní **stejný non-writing capture na druhém fyzickém VUSION/NTAG kusu**.

Porovnat zejména:

```text
0x00..0x0B   jsou stejné napříč kusy?
0x0C..0x0F   změní se podle SES ID?
0x10..0x2F   používá druhý tag stejný stream/generátor?
0x3E..0x3F   vazba na dynamickou část?
```

Tím lze rozlišit:

- globální protocol constants;
- model-specific constants;
- device-specific fields;
- per-session data.

Další vhodný experiment je sbírat více cyklů za přesně kontrolovaných podmínek a hledat vztah mezi opakovanými 16B okny. Stále není potřeba provádět žádný persistentní zápis.
