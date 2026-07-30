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
