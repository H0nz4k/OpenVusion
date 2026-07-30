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
