# HWSniff — field capture log

This document records selected physical field captures and keeps **observed data** separate from protocol hypotheses.

## 2026-08-06 — Penny Market — SOLUM 2.6" ESL

A physical HWSniff v2 capture was collected from a SOLUM electronic shelf label in Penny Market.

The photographed hardware matches the same SOLUM family previously observed in Albert:

```text
Manufacturer: SOLUM
Model: EL026F3BYA
FCC ID: 2AFWN-EL026F3WRA
IC: 22800-EL026F3WRA
MFD marking on photographed reference: Jul.09.2023
Silabs marking present
```

The visual front layout differed between shelf labels (standard white layout vs yellow promotional layout), but the hardware family appears to be the same.

### Capture artifact

Field capture archive:

```text
06082026_14_13_79ecd3353cef.tar
```

Capture start:

```text
2026-08-06T12:13:09Z
```

Reader:

```text
Port: /dev/ttyS0
Version: TWN4/B1.64/NCF5.20/PRS1.04
Device type: 11
```

### Detected tag

```text
UID / ID: 02FE42316D8E4C8B
TWN4 tag_type: 0x85 (133)
ID length: 64 bit / 8 bytes
```

Tag detection succeeded immediately.

### UID confirmation

The same 64-bit identifier was confirmed three times:

```text
02FE42316D8E4C8B
02FE42316D8E4C8B
02FE42316D8E4C8B
```

Result:

```text
3 / 3 confirmed
```

Observed confirmation latency was approximately 495 ms per attempt.

### SweetP positioning quality

The field positioning was strong, so later NTAG-specific timeouts cannot reasonably be explained as poor placement alone.

```text
score_at_accept: 98.592
band_at_accept: good
minimum: 55.0
maximum: 98.592
average: 85.227
sample_count: 16
```

### NTAG-specific identification attempt

Current HWSniff identification still attempted NTAG `GET_VERSION` (`0x60`).

All three attempts timed out:

```text
attempt 1: Tag neodpověděl na příkaz 60.
attempt 2: Tag neodpověděl na příkaz 60.
attempt 3: Tag neodpověděl na příkaz 60.
```

Phase result:

```text
identification = serial_timeout
```

### NTAG Type-2 READ attempt

The current application phase also attempted:

```text
30 00
```

All three attempts timed out.

The collector therefore classified the NTAG-specific phases as unsupported:

```text
eeprom     = unsupported
application = unsupported
session    = unsupported
```

Verification of the locked UID still succeeded at the end of the capture.

### Overall result

```text
overall_status = PARTIAL
```

This is a **useful partial capture**, not a failed detection. The tag is found reliably and its identifier remains stable; the unsupported result is caused by applying NTAG/Type-2 follow-up commands to a tag that appears to use another NFC technology.

## Cross-store SOLUM fingerprint

The Penny sample reproduces the same high-level fingerprint already observed on two SOLUM samples from Albert.

### Albert sample A

```text
ID: 02FE422D65035909
tag_type: 0x85
ID length: 64 bit
```

### Albert sample B

```text
ID: 02FE422D7723EF1B
tag_type: 0x85
ID length: 64 bit
```

### Penny sample C

```text
ID: 02FE42316D8E4C8B
tag_type: 0x85
ID length: 64 bit
```

Across all three physical samples:

- TWN4 detects the target;
- the returned identifier is 8 bytes / 64 bits;
- `tag_type` is consistently `0x85`;
- UID confirmation is stable;
- NTAG `GET_VERSION (0x60)` does not produce the expected NTAG response;
- NTAG Type-2 `READ (0x30 0x00)` does not produce the expected response.

This makes the SOLUM fingerprint reproducible across at least two different retail environments.

## Current NFC hypothesis

The strongest current hypothesis remains:

```text
probable NFC family: FeliCa / NFC Forum Type 3
confidence: high hypothesis, not yet protocol-confirmed
```

Reasons:

- SOLUM documentation for relevant Newton ESL families references FeliCa / NFC Forum Type 3 support;
- the observed ID length is consistent with an 8-byte FeliCa IDm-sized identifier;
- multiple physical tags show the same non-NTAG behavior;
- the existing TWN4 reader detects the tags reliably.

Do **not** hard-code `0x85 == FeliCa` solely from these captures. Confirmation should come from an ELATEC tag-type mapping and/or a successful FeliCa-native probe.

## Recommended next experiment

Before integrating any new branch into HWSniff v2, use a physical SOLUM tag on a PC with the existing ELATEC TWN4 and ElaTool/PCSniff codebase.

Implement a standalone **read-only FeliCa probe** first.

Desired progression:

```text
reader detect
→ SearchTag / current 0x85 + 64-bit ID observation
→ FeliCa-native polling / identification
→ retrieve IDm / PMm if supported
→ request system-code/service information if supported
→ optionally perform Read Without Encryption only on clearly public/readable services
→ save raw request/response evidence
```

No write, authentication-bypass, emulation or destructive operation belongs in the first experiment.

If the PC experiment confirms FeliCa behavior, only then should the shared capture engine gain a technology-dispatch branch and HWSniff consume it.

## Research rule

For each new field capture, preserve:

- source/date/context;
- hardware markings when known;
- raw archive name;
- reader firmware/version;
- tag type;
- ID length and value;
- confirmation attempts;
- positioning quality;
- commands attempted;
- raw responses/timeouts;
- final status;
- confirmed facts vs hypotheses.
