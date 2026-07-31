# HWSniff Architecture

Touchscreen field appliance for **read-only** NFC capture of VUSION tags
using one ELATEC TWN4 reader on Raspberry Pi OS.

## Layers

```text
┌─────────────────────────────────────────┐
│  HWSniff UI (pygame fullscreen)         │  state machine, touch
├─────────────────────────────────────────┤
│  HWSniff orchestration                  │  START/STOP, SweetP, storage
├─────────────────────────────────────────┤
│  SweetPService (position probe)         │  RO stability, no captures
│  CollectorService (field capture)       │  continuous field collection
├─────────────────────────────────────────┤
│  elatec_uid_tool.field_collector        │  capture, index, SHA-256
│  elatec_uid_tool protocol / ntag        │  SearchTag, GET_VERSION,
│                                         │  READ/FAST_READ (RO)
└─────────────────────────────────────────┘
```

HWSniff **does not** reimplement TWN4 protocol, CRC, EEPROM reads, or
manifest logic. Field capture imports ElaTool’s Field Collector API; SweetP
uses the same read-only `NtagI2CPlus` helpers without writing capture packages.

## Target paths (Raspberry Pi)

| Role | Path |
|---|---|
| App install | `/opt/Sniff` |
| Vendored ElaTool | `/opt/Sniff/vendor/ElaTool` |
| venv | `/opt/Sniff/.venv` |
| Config | `/etc/hwsniff/config.json` |
| Data | `/var/lib/hwsniff` |
| Captures | `/var/lib/hwsniff/captures` |
| Logs | `/var/log/hwsniff` |
| Runtime | `/run/hwsniff` |

## Process model

- systemd unit `hwsniff.service` runs as user `hwsniff`
- UI thread renders state; collector worker thread emits events via queue
- SIGTERM → clean STOP (finish in-flight capture when possible)

## NFC safety

Strict read-only. No WRITE / FAST_WRITE / PWD_AUTH / session writes /
pass-through / SRAM.

## Prior research context

Trigger Analysis concluded general RF/select association, not a magic
command. Field collection focuses on EEPROM + identification datasets.
