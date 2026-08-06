# HWSniff v2 — automatic NTAG / FeliCa dispatch

Status: implemented on `cursor/pi-zero-gpio-shared-capture`.

HWSniff continues to use the same shared ElaTool `CaptureProbe` engine. The public
`CaptureProbe` export is now technology-aware and automatically chooses the
correct read-only branch after a tag is locked.

## Goal

The field appliance must not send NTAG-specific commands to every ESL.

Desired flow:

```text
SearchTag / lock target
        |
        +-- normal known NTAG-sized target
        |       -> existing NTAG I2C Plus path
        |
        +-- 8-byte ID or observed tag_type 0x85
                -> try native FeliCa Poll
                -> confirm only if Poll succeeds AND IDm == locked SearchTag ID
                -> FeliCa / NFC Forum Type 3 branch
                -> otherwise fall back to original NTAG identification
```

`tag_type == 0x85` is only a hint. It is never the proof of FeliCa.

## Physically verified SOLUM fingerprint

The implementation is based on the physical SOLUM sample verified on
2026-08-06:

```text
SearchTag tag_type = 0x85
SearchTag ID       = 02FE42316D8E4C8B
FeliCa IDm         = 02FE42316D8E4C8B
PMm                = FFFF000000FFFF00
System Code        = 0x12FC
NDEF RO service    = 0x000B
```

Native FeliCa Poll is the decisive technology confirmation.

## FeliCa branch

The FeliCa branch is strictly read-only.

### Phase 1 — UID confirmation

Unchanged shared-engine UID confirmation.

### Phase 2 — identification / technology dispatch

For a FeliCa candidate:

```text
Poll(FFFF)
-> require IDm == SearchTag ID
-> RequestSystemCode
-> Poll(12FC) when 0x12FC is listed OR as soft fallback if listing is empty/flaky
-> require same IDm
-> RequestService(000B) as diagnostic only
-> direct CHECK / Read Without Encryption, block 0
```

Important physical finding encoded in the implementation:

```text
RequestService(000B) == false
```

does **not** prevent direct CHECK. The tested SOLUM target behaves exactly this
way. `RequestSystemCode` alone also must not hard-gate NDEF: if it returns no
codes, the probe still attempts `Poll(0x12FC)` before giving up on public reads.

Block 0 is parsed as NFC Forum Type 3 Attribute Information Block.

### Phase 3 — public memory

When system `0x12FC` and a valid Attribute Block are available, HWSniff reads
service `0x000B`, blocks `0..Nmaxb`.

For the physical SOLUM sample:

```text
Nmaxb = 60
61 x 16-byte blocks = 976 bytes including Attribute Block
```

The raw complete public area is saved as:

```text
felica_public.bin
```

The `eeprom` phase JSON retains the existing HWSniff six-step phase contract but
contains `mode = felica_type3_public`; it is not claiming that FeliCa memory is
NTAG EEPROM.

Each block read re-selects `0x12FC` and verifies the same IDm. This follows the
robust behavior discovered during the 120-second physical watcher test.

### Phase 4 — metadata

For SOLUM-sized Type-3 areas (`Nmaxb >= 56`), blocks `54..56` are retained as the
vendor-tail research area. They are also captured when the full public dump is
disabled.

The current sample contains:

```text
54: 000000000000000060E2CC67000DCF46
55: 5872D9000000000DCF46580600000000
56: 7F000000000000000000000000000000
```

Research candidates are recorded as hypotheses only, including the six-byte
boundary value:

```text
0DCF465872D9
```

and the little-endian 32-bit value from block 54 bytes 8..11.

No MAC-address, timestamp or RF-key meaning is asserted by the capture engine.

### Phase 5 — session

The NTAG I2C session-register phase has no equivalent in this Type-3 capture and
is marked `SKIPPED` for confirmed FeliCa. This is intentional and permits a
complete FeliCa capture to finish as `SUCCESS`.

### Phase 6 — verification

HWSniff:

- re-Polls `0x12FC`;
- verifies the same IDm;
- re-reads block 0;
- re-reads captured vendor-tail blocks `54..56` when present;
- compares them with the initial capture.

## NTAG branch

The original known-good NTAG I2C Plus flow remains unchanged:

```text
GET_VERSION
-> full EEPROM
-> application area
-> NTAG session registers
-> verification
```

The reference NTAG I2C Plus 1K capture must continue to pass unchanged.

## HWSniff / shared-engine integration

The implementation lives in ElaTool because PCSniff and HWSniff intentionally
share one capture engine:

```text
tools/ElaTool/src/elatec_uid_tool/readonly_capture/felica.py
tools/ElaTool/src/elatec_uid_tool/readonly_capture/auto_probe.py
```

`readonly_capture.__init__` now exports `AutoCaptureProbe` under the existing
public name `CaptureProbe`, so existing consumers do not need a second protocol
implementation.

HWSniff continues to call:

```text
FieldCollector -> CaptureProbe
```

but that probe now performs technology dispatch internally.

`summary.json` receives:

```text
technology = felica_type3 | ntag_i2c_plus | unknown
technology_dispatch = {...}
```

For FeliCa captures it also contains `felica`, `felica_public` and
`felica_metadata` sections. The FieldCollector bridge exposes the detected
technology in `FieldCaptureResult.metadata`.

## Safety invariants

The FeliCa implementation deliberately contains no write path:

- no service `0x0009`;
- no Write Without Encryption;
- no service brute-force;
- no authentication bypass;
- no emulation;
- no key extraction;
- every selected FeliCa target must keep the locked IDm;
- `RequestService=false` is diagnostic, not permission to try other services.

## Tests

`tests/test_felica_auto_dispatch.py` models the exact physically observed SOLUM
behavior, including:

```text
RequestService(000B) -> false
CHECK(000B, block 0) -> success
```

It verifies both direct shared-engine capture and the `FieldCollector` path used
by HWSniff, and asserts that the old NTAG/ISO14443-3 method is never called for a
confirmed FeliCa target.
