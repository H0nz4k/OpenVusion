# OpenVusion HWSniff — Pi Zero 2 W (v1.0-alpha1)

**Primary target:** Raspberry Pi Zero 2 W **without display**.

- ELATEC TWN4 (USB OTG)
- 2 buttons: START / STOP
- 2-position DIP: DIP1 / DIP2
- 5 LEDs: green / yellow / red / blue / orange
- Headless Python systemd service (GPIO only)

**Not used on this platform:** LCD, touchscreen, Xorg, xinit, pygame, SDL, framebuffer, Waveshare.

Legacy Waveshare 3.5" touch UI remains under `hwsniff.legacy` (`python -m hwsniff --legacy-ui`).

## GPIO map

| Function | BCM GPIO | Physical pin | Notes |
|----------|----------|--------------|--------|
| START    | 17       | 11           | to GND, pull-up, active low |
| STOP     | 27       | 13           | to GND, pull-up, active low |
| DIP1     | 22       | 15           | to GND, pull-up; ON=LOW |
| DIP2     | 18       | 12           | to GND, pull-up; ON=LOW |
| GREEN    | 5        | 29           | GPIO→330Ω→LED→GND, active high |
| YELLOW   | 6        | 31           | same |
| RED      | 12       | 32           | same |
| BLUE     | 13       | 33           | WLAN status (independent) |
| ORANGE   | 19       | 35           | Sweet Point medium quality |

```text
GPIO17 ── START ── GND
GPIO27 ── STOP  ── GND
GPIO22 ── DIP1 ── GND
GPIO18 ── DIP2 ── GND
GPIO5  ── 330R ── GREEN LED ── GND
GPIO6  ── 330R ── YELLOW LED ── GND
GPIO12 ── 330R ── RED LED ── GND
GPIO13 ── 330R ── BLUE LED ── GND
GPIO19 ── 330R ── ORANGE LED ── GND
```

## LED meanings

### MAIN MODE (DIP1 OFF)

| LED | Meaning |
|-----|---------|
| Green | READY (solid) / SUCCESS_WAIT_ACK (with orange) / cancel confirm |
| Yellow | WAITING (slow) / READING (fast) / SAVING (solid) |
| Red | ERROR / PARTIAL (slow) / cancel (single flash) |
| Blue | WLAN offline / connecting (slow) / connected |
| Orange | SUCCESS_WAIT_ACK (solid with green); otherwise off |

### SWEET POINT MODE (DIP1 ON)

| LED | Meaning |
|-----|---------|
| Green | high quality |
| Orange | medium quality |
| Red | low quality |
| Yellow | always OFF |
| Blue | WLAN (unchanged) |

No tag → green / orange / red all OFF.

## DIP modes

| DIP1 | Mode |
|------|------|
| OFF | `MODE_MAIN` — capture workflow |
| ON | `MODE_SWEET_POINT` — quality indication (MockSweetPoint in alpha1) |

DIP2 is **RESERVED** (ignored). DIP changes apply immediately and take priority over START.

## Install / deploy (Pi Zero 2 W)

See **[deploy/README.md](deploy/README.md)**.

```powershell
# Windows — daily code update over SSH:
cd tools\HWSniff\deploy
copy deploy.env.example deploy.env   # once: set HWSNIFF_PI=user@IP
.\deploy-to-pi.ps1                   # Quick sync + restart

# First install on a clean Pi:
.\deploy-to-pi.ps1 -Target pi@IP -Mode Full
```

This installs **no** Xorg/Waveshare/pygame.

## GPIO test

```bash
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
# on a PC / CI:
python -m hwsniff --gpio-test --mock-gpio
```

## Run service

```bash
sudo systemctl enable --now hwsniff
journalctl -u hwsniff -f
```

Unit: `systemd/hwsniff-gpio.service` (installed as `hwsniff.service`).

## Alpha1 behaviour

**MAIN**
- READY = green solid
- START → WAITING (yellow slow); START again → mock READING → SAVING → `SUCCESS_WAIT_ACK`
- `SUCCESS_WAIT_ACK`: green+orange solid, no timeout; START/STOP = ACK → health check → READY (does not start capture)
- Short STOP / long STOP (3 s) during a cycle → abort → red single → green confirm → READY
- Long STOP = „zastav vše, od začátku MAIN“ → READY (power vypíná samostatný hardwarový spínač, ne GPIO)

**SWEET POINT**
- DIP1 ON enters immediately; MAIN capture cannot start; START ignored
- MockSweetPoint cycles none / low / medium / high for LED validation
- DIP1 OFF → stop monitoring, health check, MAIN READY

Collector remains `MockCollector` (no real ElaTool capture in alpha1).

## Tests

```bash
cd tools/HWSniff
PYTHONPATH=src:../ElaTool/src python -m unittest discover -s tests -v
```

## Legacy touchscreen

```bash
python -m hwsniff --legacy-ui
# old installer: install.sh / safe-update.sh / hwsniff-x11.service
```
