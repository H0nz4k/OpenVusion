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
