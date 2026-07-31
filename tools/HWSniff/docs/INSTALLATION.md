# HWSniff Installation

## Prerequisites

- Raspberry Pi OS (Bookworm recommended) or Debian-like
- Waveshare 3.5" LCD (B) connected per vendor docs
- ELATEC TWN4 on USB
- Network only for initial `apt` / package install (runtime is offline-capable)

## Clean install

```bash
# From OpenVusion repo checkout
sudo bash tools/HWSniff/install.sh
```

Optional flags:

```bash
sudo bash tools/HWSniff/install.sh --configure-display
sudo bash tools/HWSniff/install.sh --skip-display-config
sudo bash tools/HWSniff/install.sh --no-start
```

Installer is idempotent. Existing `/etc/hwsniff/config.json` is preserved;
updates write `config.json.new` / keep `.example`.

## After install

```bash
sudo systemctl enable --now hwsniff
sudo systemctl status hwsniff
/opt/Sniff/scripts/diagnose.sh
```

Reboot is **not** automatic; confirm manually if display overlays changed:

```bash
sudo reboot
```

## Safe update (recommended on Pi)

Use the guardian — one command:

```bash
cd /opt/OpenVusion
sudo bash tools/HWSniff/safe-update.sh --restart
```

Flow: snapshot protected files → `sudo git pull --ff-only` (as root) →
`update.sh --code-only` → verify unit/config/wrapper → restore if drifted →
optional restart.

Standalone pull on the Pi:

```bash
cd /opt/OpenVusion
sudo git pull --ff-only
```

Protected paths:
- `/etc/systemd/system/hwsniff.service`
- `/etc/hwsniff/config.json`
- `/etc/hwsniff/display.env` (if present)
- `/opt/Sniff/scripts/start-hwsniff-appliance.sh`

**Do not** re-run `install.sh` for code updates. Never pass `--update-unit`
or `--force-unit` on a working Waveshare appliance.

Lower-level (no git pull): `sudo bash tools/HWSniff/update.sh --code-only`

## Paths

| Path | Purpose |
|---|---|
| `/opt/Sniff` | Application + venv |
| `/etc/hwsniff/config.json` | Config |
| `/var/lib/hwsniff` | Captures + index |
| `/var/log/hwsniff` | Logs |

## Display note

Waveshare overlays vary by Pi model and OS. Installer never guesses VID/PID
or dtoverlay values. Use `--configure-display` only after verifying the
vendor procedure for your exact LCD SKU, or configure display manually and
run with `--skip-display-config`.
