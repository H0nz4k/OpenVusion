# Application Block Analysis

Pasivní read-only analýza EEPROM stránek `0x30`–`0x37` (32 bajtů)
na NTAG I²C Plus 1K / VUSION štítcích.

## Rozsah

```text
page 0x30 … 0x37  →  8 × 4 B = 32 B
```

Referenční obsah (ověřený dump):

```text
0x30: A0 81 FF FF
0x31: FF FF FF FF
0x32: FF FF FF FF
0x33: C9 D0 2C AA
0x34: FF 3A 10 00
0x35: 00 33 00 02
0x36: 01 0D 02 02
0x37: D5 01 6C 93
```

## Potvrzený fakt

```text
NDEF identifier: AA2CD0C9
EEPROM 0x33:     C9 D0 2C AA
```

Označení: **confirmed little-endian identifier match**.

## CLI

Čtení z tagu:

```bash
python -m elatec_uid_tool application-block --port COM6
```

Analýza dumpu:

```bash
python -m elatec_uid_tool analyze-application-block dump.json
python -m elatec_uid_tool analyze-application-block dump.bin --start-page 0x30
```

Porovnání:

```bash
python -m elatec_uid_tool compare-application-blocks dump1.json dump2.json
```

## Výstupy analýzy

- raw stránky / bajty / absolutní offsety;
- ASCII náhled;
- LE/BE 16bit a 32bit pohledy;
- nulové, `0xFF` a nenulové pozice;
- opakující se vzory;
- bitové statistiky;
- confirmed NDEF ID match;
- checksum/CRC kandidáti (nikoli důkaz z jedné shody);
- hypotézy oddělené od faktů.

## Checksum kandidáti

Testuje se omezená sada přes různé řezy bloku:

- CRC-8 (ATM, Maxim/Dallas);
- CRC-16/IBM, CRC-16/CCITT-FALSE, CRC-16/X25;
- součet mod 256 / 65536;
- XOR;
- one's complement sum.

Jediná shoda na jednom dumpu = kandidát, ne důkaz.

## Porovnání dumpů

- konstantní vs. proměnné pozice;
- změny po stránkách a bajtech;
- korelace s NDEF ID;
- kandidátní čítače / timestampy / checksum pole.

## Bezpečnost

Pouze `SearchTag`, `GET_VERSION`, `READ` / `FAST_READ`. Žádný zápis.
