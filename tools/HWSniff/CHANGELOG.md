# Changelog

## [Unreleased]

### Added

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
