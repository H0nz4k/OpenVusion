# HWSniff — tag technology findings

This document records field observations and separates **confirmed facts** from **working hypotheses**.

The goal is to avoid forcing every detected ESL/tag through the NTAG I²C path when the underlying NFC technology is different.

## Confirmed family: NTAG I²C Plus 1K

A physically verified capture succeeded end-to-end with an ELATEC TWN4 and an NTAG I²C Plus 1K target.

Observed example:

```text
UID: 04367F5A2D7280
Tag type: 0x80
UID length: 56 bit
GET_VERSION: 00 04 04 05 02 02 13 03
Identification: NTAG I2C Plus 1K
```

The full read-only pipeline was physically verified:

- reader info
- tag search / UID
- UID confirmation
- identification
- complete EEPROM read
- application area
- session data
- verification
- persistence/save

The tested EEPROM capture contained 226 pages and completed successfully.

This remains the known-good reference path for HWSniff/PCSniff/ElaTool.

## Physical teardown of the known NTAG/imagotag target

A destructive teardown of the known-good tag was performed after a successful full capture.

### Confirmed PCB markings

The PCB is marked:

```text
imagotag
RFRTx024E
```

The main RF/MCU device is clearly marked:

```text
Texas Instruments
CC2510F32
```

This is a major confirmation for the RF architecture of this tag family.

### Confirmed RF capability

The CC2510F32 is a Texas Instruments 8051-based SoC with an integrated proprietary 2.4 GHz transceiver.

Therefore, for this imagotag family, 2.4 GHz operation is no longer only a hypothesis: the hardware directly confirms the presence of a 2.4 GHz RF subsystem.

Important consequence:

- this radio path is **not the same thing as the NFC/NTAG path**;
- the known NTAG I²C Plus 1K interface and the 2.4 GHz radio should be treated as separate channels;
- this particular RF architecture is based on the CC2510/CC2500 family and must not automatically be classified as IEEE 802.15.4.

The CC2510 family supports proprietary 2.4 GHz packet radio operation such as 2-FSK/GFSK/MSK-class modulation rather than being a native 802.15.4 radio.

### Architectural model after teardown

Current working model:

```text
                   +----------------------+
                   |   imagotag ESL       |
                   |                      |
NFC / service ---> | NTAG I2C Plus 1K    |
                   |          |           |
                   |          | local bus |
                   |          v           |
2.4 GHz RF <-----> | TI CC2510F32         |
                   |          |           |
                   |          +--> display electronics
                   |          +--> front indicator LEDs
                   +----------------------+
```

The exact internal connection between the NTAG and CC2510 is not yet electrically traced, so the local-bus arrow remains a working architectural inference.

### Front optical components

Two front-facing optical components are visible at the top edge of the PCB.

Based on package appearance and PCB placement, the current interpretation is:

- one likely white LED;
- one likely multi-die / RGB indicator LED.

They should currently be documented as **front indicator LEDs**, not sensors.

This remains visual identification only until electrically tested or traced.

### E-paper persistence after battery removal

Removing the battery did not clear or visibly reset the displayed image.

This must **not** be interpreted as proof that the MCU remained powered.

E-paper is bistable and normally retains its last image without power. The expected interpretation is therefore:

```text
battery removed
→ MCU/RF likely loses power and resets
→ e-paper retains the last rendered image
```

Future reset verification should use RF behavior, current consumption or another active signal rather than display persistence.

### NFC structure visible on PCB

A large printed loop/coil structure is visible on the reverse side of the PCB and is consistent with the physical presence of an NFC antenna structure.

This matches the already verified NTAG I²C Plus 1K capture path.

### Additional ICs and test points

The PCB contains:

- a small 8-pin IC adjacent to the CC2510;
- several accessible test pads;
- a crystal close to the CC2510;
- RF matching/passive components;
- e-paper flex connector;
- multiple battery contacts.

The 8-pin IC is not yet positively identified. Because the tag is already known to contain NTAG I²C Plus functionality, it is an interesting candidate for further identification, but this must not be recorded as confirmed without readable package marking or electrical tracing.

### RF investigation consequence

For this specific imagotag/CC2510 family, a pure IEEE 802.15.4 sniffer is not necessarily the correct first tool.

A more appropriate investigation path is CC2500/CC2510-compatible proprietary 2.4 GHz sniffing, for example using compatible TI tooling/hardware where available.

The desired next passive RF investigation is:

```text
identify active channel/frequency
→ determine modulation/bitrate
→ capture packet timing and framing
→ identify addresses / repeated fields
→ correlate RF traffic with known NFC UID
→ observe behavior during a real display update
```

No transmission is required for this phase; passive capture is sufficient.

### New confirmed profile for this family

```text
Vendor / family: imagotag / SES-imagotag family
PCB marking: RFRTx024E
Main MCU/RF: TI CC2510F32
RF band: 2.4 GHz proprietary radio
NFC: NTAG I2C Plus 1K (physically verified by capture)
Display: e-paper, image persists without battery power
Front optics: likely indicator LEDs; exact type not yet electrically verified
```

This family should now be treated as a dual-interface target:

```text
NFC reconnaissance / memory capture
+
proprietary 2.4 GHz RF reconnaissance
```

## Field finding: SOLUM ESL in Albert

Field testing on 2026-08-05 found electronic shelf labels in an Albert store that do **not** behave like the known NTAG I²C Plus target.

Photographed rear label:

```text
Manufacturer: SOLUM
Model: EL026F3BYA
FCC ID: 2AFWN-EL026F3WRA
IC: 22800-EL026F3WRA
MFD: Jul.09.2023
Silabs marking present
```

Two captures from this family produced different IDs but the same high-level behavior.

Observed examples:

```text
UID / ID: 02FE422D65035909
Tag type: 0x85
ID length: 64 bit
```

and

```text
UID / ID: 02FE422D7723EF1B
Tag type: 0x85
ID length: 64 bit
```

### Confirmed observations

- TWN4 detects the tag.
- An 8-byte / 64-bit identifier is returned.
- UID confirmation succeeds.
- The current NTAG-specific follow-up probes do not work.
- NTAG `GET_VERSION` (`0x60`) does not return the expected NTAG response.
- NTAG Type 2 `READ` (`0x30 0x00`) does not return the expected response.
- The existing classification therefore correctly concludes that the tag is **not behaving like NTAG I²C Plus**.

These captures must not be treated simply as failed NTAG reads. The technology branch is likely different.

## Working hypothesis: FeliCa / NFC Forum Type 3

The strongest current hypothesis is that the SOLUM label exposes **FeliCa / NFC Forum Type 3** functionality on its NFC interface.

Evidence supporting the hypothesis:

1. The photographed device is a SOLUM ESL from a product family associated with NFC/FeliCa-capable labels.
2. The observed identifier is 64 bit / 8 bytes, which is consistent with a FeliCa IDm-sized identifier.
3. The ELATEC TWN4 can see the target, but NTAG/Type-2 commands do not produce the expected responses.
4. The behavior is consistent across two separate field captures of this SOLUM family.

### Confidence level

**Strong hypothesis, not yet protocol-confirmed.**

Do not hard-code `tag_type 0x85 == FeliCa` until the ELATEC tag-type mapping or a successful FeliCa-native probe confirms it.

## Important architectural consequence

Tag discovery and tag-specific read logic must be separated.

The desired flow is:

```text
SearchTag / detect target
        |
        +-- known NTAG / Type 2 family
        |       -> existing NTAG I2C capture path
        |
        +-- probable FeliCa / Type 3 family
        |       -> FeliCa read-only probe path
        |
        +-- unknown family
                -> generic/raw identification capture
```

Do not send NTAG-specific commands blindly to every detected tag.

## Proposed read-only FeliCa investigation

The next investigation branch should use only safe read-only/identification operations supported by the TWN4/ElaTool stack.

Candidate standard FeliCa operations to investigate:

- Polling
- Request Service
- Request Response
- Request System Code
- Read Without Encryption

Potential data to persist:

- IDm
- PMm
- System Code
- service codes
- readable blocks
- raw request/response frames
- timings
- retries
- reader/tag type metadata

This is an investigation plan, not a claim that all of these operations are currently implemented.

## Do not infer display payload from NFC

The electronic price label's main wireless update mechanism may be separate from its NFC interface. Therefore:

- NFC may expose identity, service, pairing, maintenance or auxiliary data;
- absence of the complete displayed price/product payload in NFC should not be treated as a failed capture;
- 2.4 GHz ESL communication and NFC should be investigated as separate channels.

## Capture classification guidance

For current HWSniff/ElaTool output, prefer explicit wording:

```text
technology = unknown_non_ntag
probable_family = felica_type3
confidence = hypothesis
```

rather than:

```text
NTAG read failed
```

until FeliCa-native probing is implemented and physically verified.

## Field research rule

Whenever a new physical tag family is encountered, record:

- date/location/context
- manufacturer/model markings
- reader-reported tag type
- identifier length and value
- commands attempted
- raw responses/timeouts
- what is confirmed
- what is inferred
- next safe read-only probes

For teardown work, additionally record:

- PCB identifiers/revisions
- MCU/RF part number
- radio family/band
- antenna structures
- NFC IC/antenna if identifiable
- display part number
- power architecture
- LEDs/sensors
- debug/test pads
- high-resolution photos of both PCB sides

This document should be updated as new field captures and hardware findings are obtained.
