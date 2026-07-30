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
