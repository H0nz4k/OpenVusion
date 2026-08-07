# VUSION / NTAG I2C Plus — stock-firmware NFC session handshake

Date: 2026-08-07

Status: **follow-up completed**. The `SRAM_RF_READY=1` window was subsequently captured directly, first in 3 cycles and then in 50/50 cycles. See [`VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md`](VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md).

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

This does **not** by itself identify the contents of that message. It may contain identification, status, provisioning/commissioning data, challenge/response material, configuration, or another proprietary handshake. It must not be assumed to contain an AP key.

The behavior closely matches the hardware mechanism used by the independent `fanhuanji/VUSION4.2BWR_GL340` project, which also drives NTAG I2C pass-through and SRAM from CC2510 firmware. Their application protocol is custom and must not be treated as evidence for the stock SES protocol; only the NTAG hardware mechanism is directly comparable.

## Follow-up result

The planned single-read SRAM experiment was completed successfully.

The RF-side SRAM was read exactly once while:

- `PTHRU_ON_OFF = 1`
- `TRANSFER_DIR = I2C -> NFC`
- `SRAM_RF_READY = 1`
- the same UID remained selected.

The 64-byte mailbox was captured 3/3 in the first experiment and later **50/50** in the statistical run.

Key findings from the follow-up:

- frame layout is stable: 16B header + 32B dynamic data + 14 zero bytes + 2B dynamic trailer;
- the header contains `C9 D0 2C AA`, the little-endian form of the known SES ID `AA2CD0C9` from NDEF and EEPROM;
- consuming the complete SRAM frame always clears `SRAM_RF_READY` and flips `TRANSFER_DIR` to `NFC -> I2C`;
- the dynamic 32B region has high empirical entropy but contains long exact repeated sequences across cycles, including one full 16B block recurring in another cycle/position;
- no simple 16/32-bit monotonic counter was found;
- common CRC16/checksum candidates did not explain the 2-byte trailer.

Full result and confidence classification:

[`VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md`](VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md)

## Reproducibility of the original watcher

Two consecutive watcher cycles were effectively identical:

1. ~0 ms: `NC=0x7C`, `NS=0x41`
2. ~60 ms: `NC=0x7C`, `NS=0x29`
3. ~1.20 s: `NC=0x19`, `NS=0x01`

The 50-cycle follow-up then reproduced the READY event and complete SRAM capture in every requested cycle.
