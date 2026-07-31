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
│ [ SWEETP ][ START ]│         │ OK: n  Errors: m   │
│ Status: READY      │         │     [ STOP ]       │
└────────────────────┘         └────────────────────┘
```

**SWEETP** — live read-stability / position-quality meter (not RF RSSI; no capture dataset).
See [docs/SWEETP.md](docs/SWEETP.md).

## Quick install (on Pi, once)

From an OpenVusion checkout that includes `tools/ElaTool`:

```bash
cd /path/to/OpenVusion
sudo bash tools/HWSniff/install.sh --skip-display-config
sudo systemctl status hwsniff
```

## Safe update (Waveshare / X11 appliance)

**Do not run `install.sh` for updates.** Use the guardian updater:

```bash
cd /path/to/OpenVusion
sudo bash tools/HWSniff/safe-update.sh          # pull + sync + verify
sudo bash tools/HWSniff/safe-update.sh --restart  # same, then restart
```

What `safe-update.sh` protects:
- `/etc/systemd/system/hwsniff.service` (snapshot → restore if changed)
- `/etc/hwsniff/config.json` and `display.env`
- ensures `start-hwsniff-appliance.sh` exists after sync
- never apt, never `--update-unit` / `--force-unit`

Backups land in `/var/lib/hwsniff/update-backups/<timestamp>/`.

X11 unit template (reference only): `systemd/hwsniff-x11.service`.

Optional display setup (parameterized — no guessed Waveshare overlay):

```bash
sudo bash tools/HWSniff/install.sh --configure-display
```

Export captures to a mounted USB volume:

```bash
sudo /opt/Sniff/scripts/export-data.sh /media/usb
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/INSTALLATION.md](docs/INSTALLATION.md)
- [docs/TOUCH_UI.md](docs/TOUCH_UI.md)
- [docs/READER_AUTODETECTION.md](docs/READER_AUTODETECTION.md)
- [docs/STORAGE_FORMAT.md](docs/STORAGE_FORMAT.md)
- [docs/FIELD_WORKFLOW.md](docs/FIELD_WORKFLOW.md)
- [docs/SWEETP.md](docs/SWEETP.md)

## Development tests (PC)

```bash
cd tools/HWSniff
python -m venv .venv
.venv/Scripts/pip install -e ../ElaTool -e ".[dev]"
.venv/Scripts/python -m unittest discover -s tests -v
```
