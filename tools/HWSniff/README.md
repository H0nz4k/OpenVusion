# OpenVusion HWSniff

Touchscreen field device for **read-only** NFC collection from VUSION tags
via ELATEC TWN4 on Raspberry Pi + Waveshare 3.5" LCD (B).

Install target: `/opt/Sniff`

## Purpose

- Offline operation on SD card
- No keyboard/mouse
- One-button START / STOP collection
- Auto-detect ELATEC reader (no COM/`ttyACM0` hardcoding)
- Uses ElaTool Field Collector API (no protocol duplication)

## UI (ASCII)

```text
READY                          SNIFFING ACTIVE
┌────────────────────┐         ┌────────────────────┐
│ OpenVusion HWSniff │         │ SNIFFING ACTIVE    │
│ READER READY       │         │ Přiložte štítek    │
│ Storage: 24.3 GB   │         │ Last UID: …        │
│      [ START ]     │         │ OK: n  Errors: m   │
│ Status: READY      │         │     [ STOP ]       │
└────────────────────┘         └────────────────────┘
```

## Quick install (on Pi)

```bash
sudo bash tools/HWSniff/install.sh
sudo systemctl status hwsniff
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/INSTALLATION.md](docs/INSTALLATION.md)
- [docs/TOUCH_UI.md](docs/TOUCH_UI.md)
- [docs/READER_AUTODETECTION.md](docs/READER_AUTODETECTION.md)
- [docs/STORAGE_FORMAT.md](docs/STORAGE_FORMAT.md)
- [docs/FIELD_WORKFLOW.md](docs/FIELD_WORKFLOW.md)

## Development tests (PC)

```bash
cd tools/HWSniff
python -m venv .venv
.venv/Scripts/pip install -e ../ElaTool -e ".[dev]"
.venv/Scripts/python -m unittest discover -s tests -v
```
