# VUSION / NTAG I2C Plus — stock-firmware NFC session handshake

Date: 2026-08-07

## Device under test

- SES-imagotag / VUSION 2.6 family
- MCU/radio: TI CC2510F32
- NFC: NTAG I2C Plus 1K
- UID: `04367F5A2D7280`
- GET_VERSION: `00 04 04 05 02 02 13 03`
- Reader: ELATEC TWN4 `TWN4/B1.64/NCF5.20/PRS1.04`

## Experiment

A strict non-writing watcher was used. It does not read SRAM and does not issue any tag WRITE command. It only:

1. turns RF off for 2 s,
2. re-selects the same tag,
3. reads GET_VERSION and persistent configuration,
4. repeatedly reads NTAG I2C Plus session pages `EC..ED` with FAST_READ.

Persistent configuration observed in both cycles:

- page `E8`: `19 00 F8 48`
- page `E9`: `08 01 01 00`

The test was repeated twice and produced the same state sequence.

## Physical result

### t ~= 0 ms

Session register bytes:

`7C 00 F8 48 08 01 41 00`

Decoded state:

- `NC_REG = 0x7C`
- `PTHRU_ON_OFF = 1`
- `TRANSFER_DIR = 0` = I2C -> NFC
- `NS_REG = 0x41`
- `RF_FIELD_PRESENT = 1`
- `I2C_LOCKED = 1`
- `RF_LOCKED = 0`
- `SRAM_RF_READY = 0`
- `SRAM_I2C_READY = 0`

Interpretation: with the NFC field present, the stock MCU has already changed the session `NC_REG` away from the persistent value `0x19`, enabled pass-through and selected I2C -> NFC direction. The I2C side is initially locked while the MCU prepares the exchange.

### t ~= 60 ms

Session register bytes:

`7C 00 F8 48 08 01 29 00`

Decoded state:

- `PTHRU_ON_OFF = 1`
- `TRANSFER_DIR = I2C -> NFC`
- `RF_FIELD_PRESENT = 1`
- `I2C_LOCKED = 0`
- `RF_LOCKED = 1`
- `SRAM_RF_READY = 1`
- `SRAM_I2C_READY = 0`

This state persisted for approximately 1.14 s.

Interpretation: the stock CC2510 firmware has prepared SRAM content on the I2C side and handed it to the RF/NFC side. This is direct physical evidence that the original firmware actively uses NTAG I2C Plus SRAM pass-through, rather than using the NTAG only as static EEPROM/NDEF storage.

### t ~= 1.20 s

Session register bytes:

`19 00 F8 48 08 01 01 00`

Decoded state:

- `NC_REG = 0x19`
- `PTHRU_ON_OFF = 0`
- `TRANSFER_DIR = NFC -> I2C`
- `RF_FIELD_PRESENT = 1`
- locks cleared
- SRAM ready flags cleared

Interpretation: no RF-side handshake data was consumed by the watcher, so the stock firmware times out after roughly 1.2 s, disables pass-through and returns the session register to the persistent configuration while the NFC field remains present.

## Significance

This is a strong architectural finding:

```text
NFC reader
    <->
NTAG I2C Plus RF interface
    <-> 64-byte SRAM pass-through
CC2510 stock firmware
    <->
2.4 GHz / display / local state
```

The original VUSION firmware therefore reacts to NFC field activation and deliberately stages a transient message for an NFC reader.

This does **not** yet identify the contents of that message. It may contain identification, status, provisioning/commissioning data, challenge/response material, configuration, or another proprietary handshake. It must not be assumed to contain an AP key.

The behavior closely matches the hardware mechanism used by the independent `fanhuanji/VUSION4.2BWR_GL340` project, which also drives NTAG I2C pass-through and SRAM from CC2510 firmware. Their application protocol is custom and must not be treated as evidence for the stock SES protocol; only the NTAG hardware mechanism is directly comparable.

## Next safe experiment

The next non-writing test should wait for this exact state:

- `PTHRU_ON_OFF = 1`
- `TRANSFER_DIR = I2C -> NFC`
- `SRAM_RF_READY = 1`
- same UID still selected

Then perform exactly one RF read of the mapped NTAG SRAM (`F0..FF`, 64 bytes), store the result, and continue watching session state without sending any NFC WRITE.

A full `F0..FF` read is expected to consume/acknowledge the staged SRAM frame at the NTAG state-machine level, so it is not behaviorally passive, but it remains non-writing and should not alter persistent EEPROM. The result should be compared across multiple fresh RF-off/RF-on cycles to separate constant fields from per-session nonces/challenges.

Useful analysis after capture:

- compare 64-byte frames across cycles byte-by-byte,
- identify constant vs changing offsets,
- look for UID/device identifiers in normal/reversed order,
- inspect end-of-frame counters/commands/CRC candidates,
- correlate any changing field with cycle timing,
- do not label any bytes as AP key/key material without independent evidence.

## Reproducibility

Two consecutive cycles were effectively identical:

1. ~0 ms: `NC=0x7C`, `NS=0x41`
2. ~60 ms: `NC=0x7C`, `NS=0x29`
3. ~1.20 s: `NC=0x19`, `NS=0x01`

This makes the event suitable for deterministic SRAM capture in a follow-up script.
