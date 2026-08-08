# Changelog

## [2.1.0] — 2026-08-06

### Added

- **Automatic multi-technology capture** via shared ElaTool `CaptureProbe`
  (`AutoCaptureProbe`): NTAG I²C Plus and FeliCa / NFC Forum Type 3.
- Physically verified **SOLUM FeliCa Type 3** path:
  - SearchTag `0x85` is only a probe trigger (not confirmation)
  - confirmation requires native `FeliCa_Poll` + IDm == locked SearchTag ID
  - NDEF system code `0x12FC`, public RO service `0x000B`
  - full public Type-3 dump (`felica_public.bin`, Nmaxb=60 → 976 B)
  - FeliCa IDm guard on Poll and every CHECK
  - `RequestService(0x000B)=false` treated as diagnostic only (SOLUM quirk;
    never hard-gates Read Without Encryption / CHECK)
  - session phase **SKIPPED** for FeliCa (NTAG session regs not applicable)
- Deterministic Pi ElaTool upgrade: `install.sh` / `update.sh` /
  `safe-update.sh` sync + `pip install -e` from `/opt/Sniff/_vendor/ElaTool`
  (same tree as `deploy/`), with smoke import of FeliCa auto-dispatch.

### Preserved

- Original NTAG I²C Plus capture engine (UID confirm → GET_VERSION → EEPROM →
  application → session → verification → SAVE) unchanged for NTAG tags.
- Strict read-only: no FeliCa WriteWithoutEncryption / service `0x0009`; no
  new NTAG write/auth paths.
- GPIO LED/state workflow, SweetP, STOP/cancel, ERROR1/2/3, SAVE.

## [Unreleased]

### Added

- Read-only VUSION/NTAG stock-session watcher documenting the physical
  `NC_REG/NS_REG` pass-through sequence and `SRAM_RF_READY` window.
- Direct physical capture of the stock VUSION 64-byte NTAG SRAM mailbox while
  `PTHRU_ON_OFF=1`, `TRANSFER_DIR=I2C->NFC` and `SRAM_RF_READY=1`.
- 50-cycle SRAM study with 50/50 successful captures, timing statistics,
  constant/dynamic byte classification and cross-cycle recurrence analysis.
- Confirmed in-frame SES identity link: SRAM bytes `C9 D0 2C AA` are the
  little-endian form of `AA2CD0C9`, matching the same tag's NDEF URI and EEPROM
  manufacturer/application block.
- Confirmed complete RF-side SRAM read consumes the transient mailbox:
  `SRAM_RF_READY` clears and `TRANSFER_DIR` flips to `NFC->I2C` in 50/50 cycles.
- Cold-boot timing campaign: 205 successful captures across OFF durations 1–60 s;
  short OFF (1–10 s) gives READY around ~0.48 s, while 15–60 s gives a distinct
  slower ~0.53–0.56 s regime, exposing a reproducible boot/retention-state signal.
- First early-boot boundary point (`OFF=15 s`, RF after only `0.25 s`) did not
  reach the normal `SRAM_RF_READY` state inside the test timeout; detailed notes
  are in `docs/VUSION_NTAG_COLD_BOOT_TIMING_2026-08-08.md`.
- Targeted cold-boot payload recurrence analysis over all 205 successful post-boot
  SRAM frames: no duplicate `A[16]`, `B[16]`, `A+B[32]` or complete `dynamic[34]`
  frame was found, including repeated 30 s and 60 s power-off cycles.
- The same 205-frame dataset still contains long exact recurrence and a full
  cross-role 16-byte repeat (`C009B == C018A`), so A/B remain structured and
  non-independent even though a fixed post-reset seed/state is not observed.
- OFF duration has negligible simple effect on `A+B` Hamming similarity, while
  READY timing changes strongly between short and long OFF regimes. Main research
  direction therefore moves from bulk NFC collection toward read-only CC2510
  stock-firmware analysis after the V2.1 boundary follow-up completes.
- Detailed recurrence result:
  `docs/VUSION_NTAG_COLD_BOOT_STATE_RECURRENCE_2026-08-08.md`.
- Research notes separating physical evidence from public-project comparison
  (`fanhuanji/VUSION4.2BWR_GL340`, `BeatSkip/SES-Imagotag-UU340`,
  OpenEPaperLink SOLUM EFR32 work, TagTinker).
- Current research index under `docs/RESEARCH_INDEX_2026-08-07.md`.
- DIP2 **WiFi upload mode**: FTP/FTPS transfer of primary export bundles with
  persistent `upload-state.json`, LED status patterns, and retry while DIP2 stays ON.
- GPIO UART reader support via `preferred_serial: "/dev/serial0"` (9600 8N1),
  with `auto_detect` fallback and clearer port-busy diagnostics.
- Export bundle mirror (`export_bundle_mirror_root`) and optional `logs/` packing
  (`include_logs_in_bundle`); primary `.tar` remains under `export_bundle_root`.
- START button on physical pin 40 / BCM 21 (pull-up, active-low).
- Initial HWSniff Raspberry Pi touchscreen appliance design and scaffolding.
- Integration with ElaTool `field_collector` read-only API.
- Reader autodetection, pygame UI state machine, systemd installer.
- **SweetP** live position-quality meter: rolling-window score, LEPŠÍ/HORŠÍ/
  STABILNÍ trend, held POSITION OK, latency-aware quality (not RF RSSI);
  no capture index / packages.
