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

All NFC/HWSniff operations used the strict read-only FeliCa path.

## Result: FeliCa works without the ESL battery

Both batteryless runs detect exactly the same target:

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

This proves that at least the FeliCa/NFC identification and Type-3 system-selection path can operate from the RF field without the main ESL battery.

## Batteryless public-memory behavior

The current HWSniff v2.1.0 per-block strategy re-Polls `0x12FC` before public reads. Without the battery, repeated immediate Poll(12FC) calls are less reliable and may return `Result=false`.

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

So the Type-3 public data is not proven to require the main battery. At minimum block 0 is physically readable while the ESL battery is removed. The reduced reliability appears related to RF/select timing or repeated re-Poll behavior, not loss of FeliCa identity.

Recommended follow-up: use a minimal read-only sequence `Poll(12FC) -> direct CHECK` without an additional Poll before every CHECK to distinguish passive memory capability from the current HWSniff re-selection timing behavior.

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

The exact electrical partition is not yet confirmed by PCB tracing, but the batteryless FeliCa operation demonstrates that NFC has an independent passive-power capability sufficient for identification and at least some Type-3 reads.

## Next NFC experiment

Before waiting for new RF hardware, perform one strict read-only batteryless test using a minimal selection sequence:

```text
SearchTag
Poll(FFFF)
RequestSystemCode
Poll(12FC)
CHECK block 0 directly
CHECK blocks 1..2 directly
CHECK blocks 54..56 directly
```

Do not insert RequestService or repeated Poll(12FC) between each block for this experiment. Compare returned bytes with the known powered dump.

If all selected blocks match while the battery is absent, passive access to the relevant public Type-3 storage is confirmed independently of the current HWSniff re-Poll timing issue.
