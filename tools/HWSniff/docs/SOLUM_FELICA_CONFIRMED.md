# SOLUM ESL — confirmed FeliCa / NFC Forum Type 3 findings

This document records the physical SOLUM ESL experiments performed on 2026-08-06. It intentionally separates **confirmed observations** from **working hypotheses**.

It supersedes older notes that described the SOLUM NFC interface only as `probable_felica_type3`.

## Hardware family

Observed rear label:

```text
Manufacturer: SOLUM
Model: EL026F3BYA
FCC ID: 2AFWN-EL026F3WRA
IC: 22800-EL026F3WRA
MFD marking on photographed reference: Jul.09.2023
Silabs marking present
```

FCC material for `EL026F3WRA` confirms operation in the 2401–2480 MHz band. The 2.4 GHz radio path and the NFC path must be treated as separate interfaces.

Useful public references:

- https://fccid.io/2AFWN-EL026F3WRA
- https://fccid.io/2AFWN-EL026F3WRA/User-Manual/User-Manual-6601051

## Reproducible SearchTag fingerprint

Three physical SOLUM samples have produced the same high-level NFC fingerprint:

```text
Albert A: 02FE422D65035909, tag_type=0x85, 64 bit
Albert B: 02FE422D7723EF1B, tag_type=0x85, 64 bit
Penny C:  02FE42316D8E4C8B, tag_type=0x85, 64 bit
```

The Penny sample was used for the detailed FeliCa tests below.

Reader:

```text
TWN4/B1.64/NCF5.20/PRS1.04
COM13
```

Target:

```text
SearchTag tag_type: 0x85
SearchTag ID:       02FE42316D8E4C8B
ID length:          64 bit / 8 bytes
```

Do not rely on `tag_type=0x85` alone as the proof of FeliCa. The decisive confirmation is the successful native FeliCa Poll and subsequent Type-3 CHECK operation.

## FeliCa physically confirmed

A native FeliCa probe succeeded:

```text
FeliCa Poll(0xFFFF)
IDm = 02FE42316D8E4C8B
PMm = FFFF000000FFFF00
```

The returned FeliCa `IDm` is **identical** to the identifier returned by TWN4 `SearchTag`.

This establishes the relationship:

```text
SearchTag ID == FeliCa IDm
```

and confirms that this physical SOLUM family exposes FeliCa / NFC-F behavior.

Repeated Polls produced the same PMm:

```text
PMm = FFFF000000FFFF00
```

## System Code

`RequestSystemCode` succeeded and returned exactly one system code:

```text
0x12FC
```

`0x12FC` is the NFC Forum Type 3 NDEF system code.

A second explicit Poll on that system also succeeded:

```text
Poll(0x12FC)
IDm = 02FE42316D8E4C8B
PMm = FFFF000000FFFF00
IDm match = true
```

The probe is therefore required to verify that the IDm after the second Poll still matches the original target before performing any further read.

## Request Response behavior

The TWN4 Simple Protocol `FeliCa_TDX` attempt used for FeliCa Request Response returned logical `Result=false`.

This does **not** invalidate the FeliCa identification because Poll, RequestSystemCode and direct CHECK all succeed.

Record this as an unsupported/false operation for this target/reader path rather than a transport failure.

## Important RequestService finding

After selecting system `0x12FC`, the probe tried:

```text
RequestService(0x000B)
```

where `0x000B` is the standard read-only NDEF service code.

TWN4 returned:

```text
Result=false
```

However, a direct standard FeliCa `Read Without Encryption` / CHECK against the **same service** succeeded.

Therefore:

> `RequestService(0x000B) == false` MUST NOT be used as a hard prerequisite for a conservative read-only CHECK.

This was physically verified, not inferred.

## Direct Type-3 block 0 read

The direct CHECK request used:

```text
service: 0x000B
block:   0x0000
```

Request frame:

```text
100602FE42316D8E4C8B010B00018000
```

The tag returned success:

```text
response_code = 0x07
IDm           = 02FE42316D8E4C8B
status_flag1  = 0x00
status_flag2  = 0x00
blocks        = 1
```

Attribute Information Block:

```text
100201003C000000000000000000004F
```

Decoded:

```text
Mapping version: 1.0
Nbr:             2
Nbw:             1
Nmaxb:           60
WriteF:          0x00
RWFlag:          0x00 (read-only)
Ln:              0 bytes
checksum:        0x004F, valid
```

Consequences:

- the NFC Forum Type 3 mapping is internally consistent;
- the public NDEF area is read-only;
- the active NDEF message length is currently zero;
- nominal data area is 60 x 16 bytes = 960 bytes, plus the 16-byte Attribute Information Block.

`Ln=0` means the bytes outside the Attribute Block must not automatically be interpreted as a current NDEF message.

## Complete public service dump

A strict read-only dump of service `0x000B`, blocks `0..60`, succeeded.

Total returned storage including block 0:

```text
61 blocks x 16 bytes = 976 bytes
```

Observed layout:

```text
block 0       Type-3 Attribute Information Block
blocks 1..53  all zero
block 54      NONZERO
block 55      NONZERO
block 56      NONZERO
blocks 57..60 all zero
```

The three non-zero blocks are:

```text
54: 000000000000000060E2CC67000DCF46
55: 5872D9000000000DCF46580600000000
56: 7F000000000000000000000000000000
```

This is a strong indication that vendor/device metadata exists near the end of the publicly readable Type-3 service area even though the active NDEF length is zero.

Do **not** call these bytes an NDEF payload while `Ln=0`.

## 120-second stability test

Blocks `54`, `55` and `56` were then sampled once per second for 120 seconds.

Robust watcher behavior:

- Poll `0x12FC` before each sample;
- verify the same IDm;
- read only blocks 54, 55 and 56;
- re-poll/retry on transient `Result=false`;
- no write commands implemented.

Final result:

```text
samples:       120
complete:      120 / 120
changes:       0
events/errors: 0
```

The values remained exactly:

```text
54: 000000000000000060E2CC67000DCF46
55: 5872D9000000000DCF46580600000000
56: 7F000000000000000000000000000000
```

Therefore these fields are at least short-term static and are unlikely to be a fast runtime counter or rapidly changing state.

An earlier watcher without per-cycle re-Poll produced a transient `Result=false` after several samples. Re-selecting system `0x12FC` and retrying made the test robust for the complete 120-second run.

## Working hypothesis: device/RF metadata

The following six-byte sequence spans the block-54 / block-55 boundary:

```text
0D CF 46 58 72 D9
```

It is exactly 6 bytes long and stayed stable throughout the watcher test.

It is a useful **candidate** for a device identifier, RF identifier, provisioning identifier or similar device-specific field.

It is **not confirmed to be a MAC address** and must not be labelled as such until comparison with additional physical tags or RF captures supports that interpretation.

A repeated sub-sequence is also visible:

```text
0D CF 46 58
```

This may indicate structured vendor metadata rather than random residual bytes.

## Working hypothesis: timestamp-like field

The byte sequence:

```text
60 E2 CC 67
```

interpreted as a little-endian 32-bit Unix value is:

```text
0x67CCE260
2025-03-09 00:35:44 UTC
```

This could be a provisioning/manufacturing/configuration timestamp, but this interpretation is **not confirmed**. It may be coincidence.

The 120-second watcher does confirm only that the value is static over that interval and is not a normal running seconds counter.

The best validation is comparison with another physical SOLUM tag.

## Working architectural hypothesis: NFC onboarding + 2.4 GHz operation

A plausible system architecture is:

```text
physical ESL
    |
    +-- NFC / FeliCa identity (IDm)
    |
    +-- proprietary 2.4 GHz radio identity / key material

commissioning handheld / phone
    -> reads NFC identity
    -> backend associates tag with store / AP / product / location
    -> normal ESL traffic continues over 2.4 GHz
```

This architecture would not require an active NDEF message. A commissioning client can use the immutable FeliCa IDm as a lookup key and keep the association in the backend.

This remains a hypothesis until observed in an actual SOLUM commissioning workflow or correlated with RF traffic.

## Encryption / key hypothesis

SOLUM product material describes AES-128 protection for the wireless ESL path.

A secret for AP/ESL communication therefore may exist in one of several forms:

- per-device key in MCU/NVM;
- store/group key;
- master-derived key;
- key provisioned during commissioning;
- backend-resolved secret where NFC exposes only an identity/reference.

The currently readable public Type-3 area does **not** look like a direct 16-byte AES key. The non-zero tail data are sparse and structured rather than resembling a full high-entropy 128-bit secret.

Current preferred interpretation:

```text
public NFC metadata -> identity/provisioning reference
secret RF key       -> likely elsewhere in device/backend
```

Do not attempt write operations or broad key extraction based solely on this hypothesis.

## Next high-value comparison

The most useful next NFC experiment is another SOLUM tag from the same family:

```text
Tag A: IDm + blocks 54..56
Tag B: IDm + blocks 54..56
Tag C: IDm + blocks 54..56
```

Compare byte-by-byte.

Interpretation guide:

- constant fields across tags -> family/configuration constants;
- changing 6-byte field -> strong device/RF identifier candidate;
- changing timestamp-like 4-byte field with plausible dates -> stronger timestamp hypothesis;
- changing values matching later RF frames -> direct NFC-to-RF identity correlation.

The candidate sequence `0DCF465872D9` should later be searched for in passive 2.4 GHz captures from the same physical ESL.

## Capture-engine consequence

Technology dispatch should now use the following logic:

```text
SearchTag
   |
   +-- known NTAG / Type 2
   |      -> existing NTAG capture path
   |
   +-- tag looks like SOLUM / tag_type 0x85
   |      -> try native FeliCa Poll
   |      -> confirm only after Poll succeeds
   |      -> RequestSystemCode
   |      -> if 0x12FC: Poll(0x12FC)
   |      -> verify same IDm
   |      -> conservative read-only CHECK
   |
   +-- unknown
          -> generic/raw identification capture
```

Do not classify FeliCa solely from the numeric `tag_type` value; use successful protocol evidence.

## Read-only safety rules used in these experiments

All scripts added with this finding are deliberately read-only:

- service `0x000B` only for public Type-3 reads;
- no `0x0009` write service;
- no Write Without Encryption;
- no service brute-force;
- no authentication bypass;
- no emulation;
- verify IDm before continuing after a system selection;
- preserve raw bytes and protocol status.

## Added helper scripts

The following standalone tools are part of this finding:

```text
tools/ElaTool/felica_direct_block0.py
tools/ElaTool/felica_dump_public.py
tools/ElaTool/felica_watch_tail_v2.py
```

Purpose:

- `felica_direct_block0.py` — prove direct read of Type-3 Attribute Block even when RequestService returns false;
- `felica_dump_public.py` — dump blocks 0..Nmaxb from public service `0x000B`;
- `felica_watch_tail_v2.py` — robustly monitor vendor-tail blocks 54..56 for changes.

These are research helpers. Shared production capture logic should still live in the common capture engine rather than being duplicated across PCSniff/HWSniff.
