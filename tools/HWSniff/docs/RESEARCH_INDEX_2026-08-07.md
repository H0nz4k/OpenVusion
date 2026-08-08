# OpenVusion / HWSniff — research index (2026-08-07)

This index links the current physical ESL research notes on branch `cursor/pi-zero-gpio-shared-capture`.

## SES / VUSION / NTAG I²C Plus

### Stock session handshake

[`VUSION_NTAG_SESSION_HANDSHAKE_2026-08-07.md`](VUSION_NTAG_SESSION_HANDSHAKE_2026-08-07.md)

Confirmed:

- stock CC2510 reacts to an NFC field;
- enables NTAG I²C Plus pass-through;
- stages data from I²C/MCU side toward RF;
- raises `SRAM_RF_READY`;
- times out and restores the persistent configuration when the frame is not consumed.

### Direct SRAM mailbox capture + 50-cycle analysis

[`VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md`](VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md)

Confirmed:

- 64-byte stock MCU->NFC mailbox captured directly;
- 50/50 fresh RF cycles successful;
- 30 fixed bytes / 34 dynamic bytes;
- SES ID `AA2CD0C9` appears in-frame as `C9 D0 2C AA`;
- full RF read consumes the ready buffer and reverses transfer direction;
- dynamic region contains long exact recurrences across sessions.

### Cold-boot timing / retention boundary

[`VUSION_NTAG_COLD_BOOT_TIMING_2026-08-08.md`](VUSION_NTAG_COLD_BOOT_TIMING_2026-08-08.md)

Confirmed on the physical VUSION sample:

- 205 consecutive captures completed successfully before the first early-boot boundary test;
- short main-power OFF intervals of 1–10 s produce `SRAM_RF_READY` around ~0.48 s;
- OFF intervals of 15–60 s move READY into a slower ~0.53–0.56 s regime;
- current transition boundary is therefore between 10 s and 15 s OFF;
- RF activation only 0.25 s after a 15 s power-off did not reach the normal `SRAM_RF_READY` state inside the test timeout;
- cold-boot timing therefore exposes an additional observable internal/retention state of the stock firmware.

### Cold-Boot State Recurrence Analysis

[`VUSION_NTAG_COLD_BOOT_STATE_RECURRENCE_2026-08-08.md`](VUSION_NTAG_COLD_BOOT_STATE_RECURRENCE_2026-08-08.md)

Výsledek cílené payloadové analýzy 205 prvních post-boot SRAM frame:

- žádný exact restart `A[16]`, `B[16]`, `A+B[32]` ani `dynamic[34]`;
- žádná duplicita 16bit traileru v 205 vzorcích;
- ani opakované 30s a 60s OFF nevrací dynamickou část na jeden pevný první stav;
- nová přesná cross-role 16B recurrence `C009B == C018A`;
- další exact recurrence 12–15 B napříč různými OFF skupinami;
- A/B nadále nejsou nezávislé fresh-random hodnoty, ale jednoduchý fixní cold-boot seed není podporován;
- obsah `A+B` nevykazuje významnou jednoduchou závislost na délce OFF, zatímco READY timing ano;
- hlavní další výzkumná větev se přesouvá na read-only analýzu stock CC2510 firmwaru.

Před debuggerem má smysl pouze jednorázově ověřit, že VDD CC2510 při dlouhém relé OFF skutečně spadne na plný power-off/POR stav.

### V2.1 boundary follow-up — částečný výsledek

[`VUSION_V21_BOUNDARY_FOLLOWUP_PARTIAL_2026-08-08.md`](VUSION_V21_BOUNDARY_FOLLOWUP_PARTIAL_2026-08-08.md)

Archiv V2.1 nedoběhl do celého plánovaného sweepu:

- `OFF=0.5 s`: 8/8 úspěšně, převážně READY ~0.48 s;
- `OFF=1 s`: 8/8 úspěšně, READY ~0.482 s;
- `OFF=2 s`: 8/8 úspěšně, READY ~0.480 s;
- `OFF=5 s`: první frame úspěšný (~0.482 s), druhý cyklus timeout;
- při timeoutu zůstal RF field aktivní, ale session stav zůstal `NC=0x19 / NS=0x01`, bez PTHRU a bez `SRAM_RF_READY` po více než 3 s;
- 25 nových úspěšných frame nemá duplicate A, B, trailer, full frame ani cross-role `A==B`;
- jemný sweep 8–18 s ani boot-before-RF sweep se kvůli stopu vůbec neprovedl.

Tento partial follow-up nemění hlavní rozhodnutí: další velký NFC/cold-boot sběr nemá vysokou informační hodnotu. Hlavní pokračování čeká na bezpečný read-only průzkum CC2510 stock firmwaru.

## SOLUM / FeliCa Type 3

### Automatic technology dispatch

[`FELICA_AUTO_DISPATCH.md`](FELICA_AUTO_DISPATCH.md)

Confirmed implementation rule:

- `tag_type=0x85` is a hint only;
- FeliCa requires native Poll confirmation and IDm guard;
- SOLUM public Type-3 system `0x12FC`, RO service `0x000B`;
- `RequestService=false` does not hard-gate direct CHECK.

### Albert physical capture

[`ALBERT_SOLUM_CAPTURE_2026-08-06.md`](ALBERT_SOLUM_CAPTURE_2026-08-06.md)

### Batteryless NFC + power cycle

[`SOLUM_NFC_BATTERYLESS_POWER_CYCLE_2026-08-06.md`](SOLUM_NFC_BATTERYLESS_POWER_CYCLE_2026-08-06.md)

Confirmed:

- FeliCa identity and Type-3 public reads work without the main ESL battery;
- one Poll(12FC) followed by direct CHECKs is more robust batteryless than re-Polling before every block;
- public Type-3 memory survived battery removal/reinstall unchanged;
- canonical device ID was correlated across NDEF, vendor tail, rear label and boot/service display.

## Related public reverse engineering

[`RELATED_ESL_RESEARCH_REFERENCES_2026-08-07.md`](RELATED_ESL_RESEARCH_REFERENCES_2026-08-07.md)

Covers:

- `fanhuanji/VUSION4.2BWR_GL340` — CC2510 + NTAG-like I²C/pass-through mechanism;
- `BeatSkip/SES-Imagotag-UU340` — different VUSION hardware generation (AX8052 + FM11 NFC);
- OpenEPaperLink SOLUM EFR32xG22 / TNB132M notes;
- TagTinker boundaries (MIFARE Ultralight/IR vs our NTAG and FeliCa branches).

## Safety / evidence rule

Every note should distinguish:

```text
PHYSICALLY CONFIRMED
STRONG INFERENCE
WORKING HYPOTHESIS
EXTERNAL REFERENCE ONLY
```

No external project is treated as proof of a stock protocol until the behavior is reproduced on the actual physical target.
