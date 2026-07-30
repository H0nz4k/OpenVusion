# OpenVusion Research


## ElaTool — NFC diagnostika a analýza

Součástí repozitáře je modul `tools/ElaTool/`.

ElaTool slouží pro komunikaci přes NFC čtečku ELATEC TWN4 a analýzu
štítků SES-imagotag VUSION používajících NTAG I²C Plus.

Aktuálně podporuje:

- detekci NFC štítku a načtení UID;
- NTAG `GET_VERSION`;
- čtení EEPROM pomocí `READ` a `FAST_READ`;
- export dumpů do BIN, JSON a TXT;
- analýzu NDEF a aplikačních dat;
- porovnávání dumpů;
- čtení konfiguračních registrů;
- monitorování session registrů;
- read-only NFC Logic Analyzer (session + SRAM timeline).

Podrobnosti jsou v [dokumentaci ElaTool](tools/ElaTool/README.md).

ElaTool je v současné fázi navržen primárně jako read-only diagnostický
a výzkumný nástroj.
