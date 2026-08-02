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
| BLUE     | 13       | 33           | WLAN status |
| ORANGE   | 19       | 35           | DIP mode |

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

| LED | Meaning |
|-----|---------|
| Green | READY / SUCCESS (triple flash) |
| Yellow | WAITING (slow) / READING (fast) / SAVING (solid) |
| Red | ERROR / PARTIAL (slow) / CANCEL (double flash) |
| Blue | WLAN offline / connecting (slow) / connected |
| Orange | DIP mode: off / solid / slow / fast |

## DIP modes (working names)

| DIP1 | DIP2 | Mode |
|------|------|------|
| OFF | OFF | `MODE_NORMAL` (orange off) |
| ON | OFF | `MODE_FAST` (orange on) |
| OFF | ON | `MODE_DEEP` (orange slow) |
| ON | ON | `MODE_SERVICE` (orange fast) |

DIP is read at boot and again on each START (not mid-cycle).

## Install (Pi Zero 2 W)

```bash
cd /path/to/OpenVusion
sudo bash tools/HWSniff/install-gpio.sh
sudo systemctl status hwsniff
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

- START in READY → WAITING (yellow slow blink)
- START again in WAITING → simulate tag → READING (mock collector ~2 s)
- STOP cancels; long STOP (4 s) → shutdown callback (`systemctl poweroff`)
- Collector is `MockCollector` with a stable interface for alpha2 ElaTool/PCSniff swap

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
