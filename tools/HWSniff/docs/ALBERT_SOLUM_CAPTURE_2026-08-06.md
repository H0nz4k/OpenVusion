# Albert SOLUM physical capture — 2026-08-06

Status: **physically captured on HWSniff 2.1.0; FeliCa Type 3 capture SUCCESS**.

This sample is important because the rear label, active NDEF message and vendor-tail
metadata can be correlated on the same physical ESL.

## Physical label

Rear label visible on the captured unit:

```text
SOLUM
MODEL: EL026F3BYA
IC: 22800-EL026F3WRA
FCC ID: 2AFWN-EL026F3WRA
MFD: Jul.09.2023
printed barcode / identifier: 09A29450C39F
additional printed code: 2379VAB001
Silabs
```

## HWSniff capture

Capture archive supplied from the physical HWSniff run:

```text
06082026_21_58_9c253c7d34b9.tar
```

Reader / transport:

```text
port: /dev/ttyS0
reader: TWN4/B1.64/NCF5.20/PRS1.04
```

Result:

```text
overall_status = SUCCESS
errors = []
technology = felica_type3
tag_type = 0x85 / FeliCa / NFC Forum Type 3
IDm = 02FE422D6F6A629E
PMm = FFFF000000FFFF00
System Code = 0x12FC
RequestService(0x000B) = false   # diagnostic only
public blocks = 61/61 OK
session = skipped
```

This is a full physical acceptance of the automatic HWSniff FeliCa dispatch on the
Pi UART path.

## Type 3 Attribute Information Block

```text
block 0 = 100201003C00000000000000001B006A
```

Decoded:

```text
NDEF mapping version = 1.0
Nbr = 2
Nbw = 1
Nmaxb = 60
WriteF = 0x00
RWFlag = 0x00 (read-only)
Ln = 27 bytes
checksum = 0x006A, valid
```

Unlike the earlier field sample with `Ln=0`, this Albert ESL contains an **active
NDEF message**.

## Active NDEF message

The first 27 bytes of blocks 1.. are:

```text
D1 01 17 55 04 61 6C 62 65 72 74 2E 63 7A 2F 30
39 41 32 39 34 35 30 43 33 39 46
```

This is an NFC Forum Well-Known URI record:

```text
URI prefix byte 0x04 = https://
payload = albert.cz/09A29450C39F
```

Therefore the complete active URI is:

```text
https://albert.cz/09A29450C39F
```

The URI suffix `09A29450C39F` **exactly matches the identifier printed below the
barcode on the physical rear label**.

This is strong evidence that NFC is intentionally exposed as a user/operator-facing
lookup/interaction mechanism tied to the ESL's externally visible device identifier.
It does not by itself prove the exact backend provisioning flow.

## Non-zero public blocks

```text
1 : D101175504616C626572742E637A2F30
2 : 39413239343530433339460000000000
3 : 69637320496E632E0000000000000000
40: 010D486F6C69746563683A3132333402
41: 0D48656E6C694D61783A313233340301
51: 02000000000000000000000000000000
52: 01000000040000000000000000000000
54: 00000000000000004C10AA640009A294
55: 50C39F0000000009A294500600000000
56: 7F000000000000000000000000000000
```

Because `Ln=27`, only the first 27 bytes starting at block 1 are part of the current
active NDEF message. Other non-zero bytes are raw public-area/vendor contents and
must not be described as part of the active NDEF payload.

Interesting ASCII outside the active NDEF length includes:

```text
block 40: Holitech:1234
block 41: HenliMax:1234
```

The exact meaning is not yet established; treat these as vendor/component metadata
until correlated with more samples.

## Vendor-tail identifier is now physically correlated

Blocks 54/55 contain this six-byte value across the block boundary:

```text
09 A2 94 50 C3 9F
=> 09A29450C39F
```

The same value occurs in all three places on the same physical ESL:

```text
rear printed barcode identifier = 09A29450C39F
active NDEF URI suffix           = 09A29450C39F
blocks 54/55 boundary value      = 09A29450C39F
```

Therefore the previous `boundary_6byte_hex` hypothesis can be upgraded:

- it is **confirmed as the externally printed per-device identifier / barcode ID**
  for this Albert SOLUM sample;
- it is also used by the active Albert NFC URL;
- whether the same six bytes are the proprietary 2.4 GHz RF address remains
  **unconfirmed** and should be tested later against RF captures.

For comparison, the earlier sample had:

```text
boundary_6byte_hex = 0DCF465872D9
```

That value should now be treated as a strong candidate for that sample's equivalent
printed/device identifier, pending a matching rear-label photo or RF correlation.

## Manufacturing timestamp correlation

Block 54 bytes 8..11 are:

```text
4C 10 AA 64
```

Interpreted as little-endian uint32:

```text
0x64AA104C = 1688866892
Unix UTC  = 2023-07-09 01:41:32
```

The physical rear label states:

```text
MFD: Jul.09.2023
```

The calendar date matches exactly.

This is **strong physical evidence** that the little-endian uint32 at block 54
bytes 8..11 is a manufacturing-related Unix timestamp. The exact semantics of the
time-of-day and timezone are not yet known, so the capture engine should continue
to label it as a research candidate rather than a guaranteed field definition.

The earlier sample contained:

```text
60 E2 CC 67 -> LE 0x67CCE260 -> 2025-03-09 00:35:44 UTC
```

That earlier timestamp hypothesis is therefore substantially strengthened; compare
it against the earlier tag's printed MFD when a rear-label image is available.

## Key conclusions

1. HWSniff 2.1.0 automatic FeliCa dispatch works physically over the Pi UART path.
2. This Albert ESL has a valid active Type-3 NDEF URI (`Ln=27`).
3. The URI points to `https://albert.cz/<device-id>`.
4. `<device-id>` exactly equals the rear printed barcode identifier.
5. The same six-byte ID is duplicated in vendor-tail blocks 54/55.
6. The block-54 LE uint32 calendar date exactly matches the printed manufacture date.
7. `RequestService(000B)=false` still does not prevent successful direct CHECK.
8. The six-byte ID may later be searched in proprietary 2.4 GHz captures, but an RF-address interpretation is not yet proven.

All observations above were obtained using read-only FeliCa operations only.
