# OpenVusion HWSniff v2 — Pi Zero 2 W

**Primary target:** Raspberry Pi Zero 2 W **without display**.

- ELATEC TWN4 (USB OTG)
- 2 buttons: START / STOP
- 2 DIP switches: DIP1 / DIP2
- 4 LEDs: green / yellow / red / blue
- Headless Python systemd service (GPIO only)
- **Real capture** via shared ElaTool `readonly_capture` engine (PCSniff parity)

**Not used:** LCD, touchscreen, Xorg, xinit, pygame, SDL, framebuffer, Waveshare.

Legacy Waveshare touch UI remains under `hwsniff.legacy` (`python -m hwsniff --legacy-ui`).

Config **must** include `hardware_profile: "v2"`. Alpha1 pin maps are rejected.

## GPIO map (v2)

| Function | Physical pin | BCM GPIO | Notes |
|----------|-------------:|---------:|--------|
| START    | **29** | 5  | switch → GND, pull-up, active-low |
| GND      | 30 | — | |
| STOP     | **31** | 6  | switch → GND, pull-up, active-low |
| DIP1     | **32** | 12 | switch → GND, pull-up, active-low |
| DIP2     | **33** | 13 | switch → GND, pull-up, active-low |
| GND      | 34 | — | |
| GREEN    | **35** | 19 | GPIO → 330 Ω → LED → GND, active-high |
| YELLOW   | **36** | 16 | same |
| RED      | **37** | 26 | same |
| BLUE     | **38** | 20 | WLAN heartbeat |
| GND      | 39 | — | |
| RESERVE  | 40 | 21 | unused |

```text
GPIO5  / pin 29 ── START ── GND
GPIO6  / pin 31 ── STOP  ── GND
GPIO12 / pin 32 ── DIP1 ── GND
GPIO13 / pin 33 ── DIP2 ── GND
GPIO19 / pin 35 ── 330Ω ── GREEN  ── GND
GPIO16 / pin 36 ── 330Ω ── YELLOW ── GND
GPIO26 / pin 37 ── 330Ω ── RED    ── GND
GPIO20 / pin 38 ── 330Ω ── BLUE   ── GND
```

## DIP modes

| DIP1 | DIP2 | Result |
|------|------|--------|
| OFF | OFF | MAIN |
| ON  | OFF | SWEETP |
| OFF | ON  | ERROR3 |
| ON  | ON  | ERROR3 |

Boot requires DIP1 OFF + DIP2 OFF, otherwise ERROR3. DIP is monitored continuously; ERROR3 recovers without restart.

## States & LEDs

| State | LEDs |
|-------|------|
| BOOT | Self-test 2×: GREEN → YELLOW → RED → BLUE (500 ms each) |
| READY | GREEN ON |
| ERROR1 | RED ON (fatal internal / SAVE failure) |
| ERROR2 | GREEN+RED sync 1 Hz (TWN4 missing; hotplug → READY) |
| ERROR3 | RED 3× 0.5 s then 1.5 s pause (invalid DIP) |
| SWEETP / POSITIONING | score bands (below) |
| READ | 6-step G/Y/R progress bar (not error colours) |
| READ COMPLETE | G+Y+R blink together 5× — tag may be removed |
| SAVE | YELLOW ON → READY GREEN on success / ERROR1 on failure |
| WLAN | BLUE short pulse every 3 s when connected |

### SweetP / POSITIONING bands

| Score | LEDs |
|------:|------|
| 75–100 | GREEN |
| 56–74 | YELLOW |
| 40–55 | YELLOW/RED alternate 250 ms |
| 0–39 | RED |
| no tag | all off |

Hysteresis default ±3. Second START (READ) only if score ≥ 56.

### READ progress bar (6 phases)

| Step | Phase | LEDs |
|-----:|-------|------|
| 1 | UID confirm | GREEN blink |
| 2 | Identification | GREEN solid |
| 3 | EEPROM | GREEN solid + YELLOW blink |
| 4 | Application | GREEN + YELLOW solid |
| 5 | Session | GREEN + YELLOW solid + RED blink |
| 6 | Verification | GREEN + YELLOW + RED solid |

## MAIN workflow

```text
READY → START → POSITIONING (live SweetP)
      → START (score ≥ 56) → READ (6 phases)
      → G+Y+R ×5 → SAVE → READY
STOP  → cooperative cancel → RED flash → READY
```

## Capture engine

HWSniff does **not** reimplement TWN4 protocol. It drives:

`ElaTool readonly_capture.CaptureProbe` ← same engine as PCSniff

One READ = one port, one tag, one locked UID. Directory stays `*_UID-pending` until serial/raw tracer close, then rename.

## Install / deploy

See **[deploy/README.md](deploy/README.md)**.

```powershell
cd tools\HWSniff\deploy
.\deploy-to-pi.ps1
```

```bash
# On Pi after install (cwd must be writable for lgpio — app also chdirs itself):
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --diagnostics
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
sudo systemctl enable --now hwsniff
journalctl -u hwsniff -f
```

Service: `WorkingDirectory=/var/lib/hwsniff` (lgpio runtime files).  
CLI also calls `ensure_runtime_cwd()` → `/var/lib/hwsniff` so `/opt/Sniff` never needs write access.  
User `hwsniff` in groups `gpio` + `dialout`.

## CLI

```bash
python -m hwsniff --config /etc/hwsniff/config.json
python -m hwsniff --gpio-test
python -m hwsniff --diagnostics
python -m hwsniff --mock-gpio          # CI / no Pi
python -m hwsniff --legacy-ui          # Waveshare UI
```

## Tests

```bash
cd tools/HWSniff
PYTHONPATH=src:../ElaTool/src python -m unittest discover -s tests -v
```

Also run ElaTool / PCSniff regression after engine changes:

```bash
cd tools/ElaTool && PYTHONPATH=src python -m unittest discover -s tests -v
cd tools/PCSniff && PYTHONPATH=src:../ElaTool/src python -m unittest discover -s tests -v
```

## Physical acceptance checklist

See end of agent report / `HW/HWSniff_v2_HW_SW_specifikace.md` — items A–T (boot, ERROR2 hotplug, SweetP, POSITIONING, READ progress, SAVE, STOP, DIP2).
