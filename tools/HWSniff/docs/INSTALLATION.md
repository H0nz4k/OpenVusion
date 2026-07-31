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
