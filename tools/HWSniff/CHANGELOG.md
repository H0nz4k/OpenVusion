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
