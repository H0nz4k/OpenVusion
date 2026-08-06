# SOLUM / Albert — NFC without battery + power-cycle observation (2026-08-06)

This note records a physical experiment on the SOLUM EL026F3BYA / Albert ESL with device ID `09A29450C39F` and FeliCa IDm `02FE422D6F6A629E`.

## Experiment sequence

1. Capture with battery installed (baseline, before power cycle).
2. Remove ESL battery completely.
3. Run two HWSniff captures without battery:
   - `06082026_22_18_db5bdc5869d5_bezbat.tar`
   - `06082026_22_19_1919829eff25_bezbat2.tar`
4. Reinstall battery.
5. Run capture after battery reinstall:
   - `06082026_22_20_8fa2d241bb49.tar`
6. Observe ESL display after battery restart.
7. Remove battery again and run a minimal PC-side read-only test with exactly one `Poll(0x12FC)` followed by direct CHECKs without any intervening re-Poll.

All NFC/HWSniff/PC operations used the strict read-only FeliCa path.

## Result: FeliCa works without the ESL battery

Batteryless runs detect exactly the same target:

```text
SearchTag tag_type = 0x85
IDm                = 02FE422D6F6A629E
PMm                = FFFF000000FFFF00
System Code        = 0x12FC
```

Batteryless raw traces physically confirm successful:

```text
SearchTag
FeliCa Poll(FFFF)
RequestSystemCode -> 0x12FC
FeliCa Poll(12FC)
```

This proves that FeliCa/NFC identification and Type-3 system selection can operate from the RF field without the main ESL battery.

## Initial HWSniff batteryless behavior

The HWSniff v2.1.0 per-block strategy re-Polls `0x12FC` before each public read. Without the battery, repeated immediate Poll(12FC) calls were less reliable and could return `Result=false`.

Batteryless capture #1 therefore finished `PARTIAL` and did not obtain Attribute block 0.

Batteryless capture #2 also had an initial block-0 failure, but later verification successfully obtained block 0 using the same strict read-only CHECK path:

```text
Attribute block 0:
100201003C00000000000000001B006A

NDEF mapping = 1.0
Nbr          = 2
Nbw          = 1
Nmaxb        = 60
RWFlag       = read-only
Ln           = 27
checksum     = valid
```

This suggested the failure was caused by repeated re-selection timing rather than by dependence of public Type-3 memory on the main battery.

## Minimal batteryless CHECK experiment — confirmed

A dedicated PC-side script then performed exactly:

```text
SearchTag
Poll(FFFF)
RequestSystemCode
Poll(12FC)        # exactly once
CHECK block 0
CHECK block 1
CHECK block 2
CHECK block 54
CHECK block 55
CHECK block 56
```

There was no `RequestService` and no additional Poll between individual CHECK operations.

Result with the ESL battery physically removed:

```text
blocks_success = 6/6
all_selected_blocks_readable = true
batteryless_public_read_evidence = STRONG
```

Every selected block succeeded on the **first CHECK attempt**:

```text
block 0   29.19 ms
block 1   29.09 ms
block 2   29.37 ms
block 54  29.15 ms
block 55  26.28 ms
block 56  28.70 ms
```

No IDm mismatch occurred and all FeliCa status flags were `0x00 / 0x00`.

The returned data exactly includes the active Type-3 Attribute/NDEF data and the known vendor tail:

```text
0:  100201003C00000000000000001B006A
1:  D101175504616C626572742E637A2F30
2:  39413239343530433339460000000000
54: 00000000000000004C10AA640009A294
55: 50C39F0000000009A294500600000000
56: 7F000000000000000000000000000000
```

The Attribute Information Block remains valid:

```text
NDEF mapping = 1.0
Nbr          = 2
Nbw          = 1
Nmaxb        = 60
RWFlag       = read-only
Ln           = 27
checksum     = 0x006A valid
```

The active NDEF record decodes to:

```text
https://albert.cz/09A29450C39F
```

and the six-byte vendor-boundary identifier remains:

```text
09A29450C39F
```

### Conclusion

This experiment strongly confirms that the relevant public NFC Forum Type 3 storage is **passively readable without the ESL main battery**. The RF field from the reader is sufficient for successful FeliCa selection and direct public-memory CHECK operations.

It also confirms that the earlier HWSniff batteryless PARTIAL results were not evidence that the Type-3 memory required the battery. They were consistent with the current strategy of re-Polling `0x12FC` before every block.

This is a strong reason to consider changing the FeliCa capture strategy from:

```text
Poll(12FC) -> CHECK one block -> Poll(12FC) -> CHECK next block -> ...
```

to a selected-session strategy such as:

```text
Poll(12FC) once
-> verify IDm
-> multiple CHECK operations
-> re-Poll only on transient failure / recovery path
```

while retaining the strict IDm guard and read-only invariant.

## Power-cycle did not modify public FeliCa memory

The complete public Type-3 dump before battery removal and the complete dump after battery reinstall are byte-for-byte identical.

```text
size   = 976 bytes
SHA256 = 8b693a46ab3b31fa55d87dcadd125c1d57e42b4795a6d7c911c03927d1223c79
```

There are zero differing bytes between the two 976-byte dumps.

Therefore:

- removing/reinstalling the battery did not alter the public Type-3 memory;
- the HWSniff read-only scans did not alter the public Type-3 memory;
- the Albert NDEF URI and vendor metadata survived the main-power cycle unchanged.

## Display after battery reinstall

After the battery was reinstalled, the ESL rebooted and the display changed to a device/service-style screen showing:

```text
m3 2.6" NEWTON BWR Normal
036
09A29450C39F
```

The screen also displays a barcode for `09A29450C39F`.

This is important because the same 12-hex-character identifier is now physically correlated across four independent locations/interfaces:

```text
rear printed label / barcode  = 09A29450C39F
boot/service display          = 09A29450C39F
NDEF URI                      = https://albert.cz/09A29450C39F
vendor-tail blocks 54/55      = 09A29450C39F
```

This strongly confirms `09A29450C39F` as a canonical per-device identifier for this ESL family.

It is still NOT yet proven to be the 2.4 GHz RF address. That correlation must come from RF capture.

## Interpretation of the display change

The display change must not be attributed to NFC writing. The OpenVusion/HWSniff FeliCa path used here contains no write command, and the complete public NFC dump is identical before and after the experiment.

The observed display change is therefore consistent with the ESL main electronics rebooting after battery reinstall and rendering an internal boot/service/default screen.

The value `036` is currently unknown. Do not label it as a product, RF, AP, store or template identifier until independently correlated.

## Architecture evidence

The physical observations now support the following model:

```text
                 +-- main MCU / display / 2.4 GHz RF -- main battery
SOLUM ESL -------|
                 +-- FeliCa / NFC-F ------------------ RF-field powered path
                          |
                          +-- IDm
                          +-- Type-3 system 0x12FC
                          +-- public read-only NDEF
                          +-- canonical device ID / vendor metadata
```

The exact electrical partition is not yet confirmed by PCB tracing, but the batteryless direct CHECK experiment shows that passive NFC-field power is sufficient not only for identification but also for the selected public Type-3 reads tested here.
