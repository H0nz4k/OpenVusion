# Related ESL reverse-engineering references — findings relevant to OpenVusion

Date: 2026-08-07

This note records useful findings from public reverse-engineering projects encountered during the current OpenVusion investigation. These sources are **comparative references**, not substitutes for physical evidence from our own tags.

The main rule is:

> Do not transfer a protocol, pinout or IC identity from another ESL family/model unless the same hardware is physically confirmed on the target under test.

## 1. fanhuanji/VUSION4.2BWR_GL340

Repository:

https://github.com/fanhuanji/VUSION4.2BWR_GL340

This project is especially relevant to the original SES/VUSION branch because it implements custom firmware for a VUSION 4.2 BWR GL340 built around a CC2510-class target and actively uses an NFC I²C/pass-through interface.

### Useful source-level findings

The project configures the NFC-side I²C bus as:

```text
SDA = P0_4
SCL = P0_6
NFC write address = 0xAA
NFC read address  = 0xAB
```

Its NFC helper definitions include session/config register concepts matching the NTAG I²C Plus style used in our physical VUSION tag:

```text
PTHRU_ON_OFF
TRANSFER_DIR
I2C_LOCKED
RF_LOCKED
SRAM_I2C_READY
SRAM_RF_READY
RF_FIELD_PRESENT
```

The custom firmware also treats SRAM as four 16-byte blocks and implements a state machine that:

```text
waits for RF field
-> enables/configures pass-through
-> stages data into SRAM
-> waits for RF-side consumption
-> reverses direction
-> receives data back from NFC side
```

That mechanism is strikingly similar to the state transitions physically observed on our stock VUSION 2.6 / NTAG I²C Plus target.

### Important boundary

The fanhuanji project runs **custom firmware** and defines its own ACK/NACK/image-transfer protocol. Therefore:

- its hardware/register use is valuable corroborating evidence;
- its application message format is **not** evidence for the stock SES-imagotag protocol;
- its commands/challenge structure must not be copied into our interpretation without independent physical confirmation.

Useful files:

- `src/nfc/i2c.h`
- `src/nfc/i2c.c`
- `src/main.c`

## 2. BeatSkip/SES-Imagotag-UU340

Repository:

https://github.com/BeatSkip/SES-Imagotag-UU340

This project documents another SES-imagotag/VUSION 2.6/2.2 hardware generation.

Reported hardware:

```text
MCU/radio: AX8052F143
NFC:       FM11NT081DS
EPD:       GDEW026Z39 or GDEW0213Z16
```

The published pin map includes an NFC chip-select and field-detect signal and a separate SPI flash.

### Consequence for OpenVusion

Our physical reference VUSION 2.6 tag is different:

```text
MCU/radio: TI CC2510F32
NFC:       NTAG I2C Plus 1K, physically verified
```

Therefore "VUSION 2.6" is not enough to identify the PCB architecture. There are materially different variants under similar product branding.

Do not import AX8052/FM11 assumptions into the CC2510/NTAG branch.

## 3. OpenEPaperLink — SOLUM EFR32xG22 support

Repositories:

- https://github.com/OpenEPaperLink/OpenEPaperLink
- https://github.com/OpenEPaperLink/Tag_FW_EFR32xG22

OpenEPaperLink has public replacement-firmware work for SOLUM M3 tags based on Silicon Labs EFR32BG22/xG22 devices.

### Useful source-level SOLUM findings

Their SOLUM hardware abstraction records:

```text
NFC field-detect: PD2
NFC SDA:          PD3
NFC SCL:          PD1
NFC power:        PD0
```

and comments that SOLUM EFR32BG22-based tags appear to use an undocumented NFC device referred to there as:

```text
TNB132M
```

The replacement firmware treats it as a separate NFC/I²C subsystem and uses field/power information around the NFC interface.

### Why this matters to our physical SOLUM findings

Our SOLUM `EL026F3BYA / EL026F3WRA` samples were physically confirmed as FeliCa / NFC Forum Type 3 via TWN4 native FeliCa Poll, system code `0x12FC` and successful Type-3 CHECK.

The OpenEPaperLink code independently reinforces the architectural idea that these SOLUM generations contain a distinct NFC subsystem connected to the main EFR32 MCU rather than merely exposing the main MCU radio directly over NFC.

It does **not** by itself prove that the exact physical EL026 sample uses the same TNB132M revision or identical pinout. PCB tracing is still required for exact part/pin confirmation.

### Debug-lock warning

The OpenEPaperLink EFR32 project also notes that some manufacturer-locked SOLUM EFR32 devices require an unlock operation before reflashing, and that such unlock can erase the original firmware.

For preservation-oriented OpenVusion research:

```text
read/identify first
never perform destructive debug unlock on an original specimen unless data loss is explicitly acceptable
```

## 4. i12bp8/TagTinker

Repository:

https://github.com/i12bp8/TagTinker

TagTinker is primarily a Flipper Zero **infrared** ESL research application. It also contains an NFC scan/decoder path.

Its current NFC decoder expects a MIFARE Ultralight/Type-2-style page layout and extracts an NDEF URI, then decodes a vendor-specific identifier from the URI.

### Boundary with our targets

This is useful as evidence that NFC identity/provisioning data are common in ESL ecosystems, but it must not be confused with either of our confirmed NFC branches:

```text
SES/VUSION reference:
  NTAG I2C Plus 1K / Type-2-style EEPROM + SRAM pass-through

SOLUM reference:
  FeliCa / NFC Forum Type 3 / system 0x12FC
```

TagTinker's MIFARE-Ultralight NDEF parser is therefore **not** a drop-in parser for the physical SOLUM FeliCa tag.

Likewise, its IR transmission protocol is unrelated to the proprietary 2.4 GHz radio paths currently under investigation in OpenVusion.

## 5. Architectural picture after combining public references with physical captures

The physically verified and externally corroborated picture now looks like this:

```text
SES / VUSION CC2510 branch
--------------------------
NFC reader
   <-> NTAG I2C Plus
       <-> 64B SRAM pass-through
           <-> CC2510 stock MCU
               <-> proprietary 2.4 GHz
               <-> display

SOLUM EFR32 branch
------------------
NFC reader
   <-> FeliCa / Type-3 NFC subsystem
       <-> EFR32 main MCU
           <-> proprietary 2.4 GHz
           <-> display
```

The two families share the broad concept of an auxiliary NFC/service path plus a separate operational radio path, but the NFC technologies and MCU families are different.

## 6. Practical rules for future research

1. Identify the exact PCB/MCU/NFC variant before applying a protocol-specific probe.
2. Keep technology dispatch protocol-confirmed rather than relying only on visual model names or TWN4 numeric `tag_type` hints.
3. Treat external reverse engineering as a hypothesis/reference layer until reproduced on the physical target.
4. Preserve stock firmware whenever possible; avoid destructive debug-unlock/erase paths during identification.
5. Keep NFC and 2.4 GHz observations separate until an identifier is physically correlated across both channels.
