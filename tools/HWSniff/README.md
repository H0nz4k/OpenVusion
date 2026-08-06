# OpenVusion HWSniff v2.1 — Pi Zero 2 W

**Primary target:** Raspberry Pi Zero 2 W **without display**.

- ELATEC TWN4 (GPIO UART `/dev/serial0` @ 9600 8N1, or USB ACM)
- 2 buttons: START / STOP
- 2 DIP switches: DIP1 / DIP2
- 4 LEDs: green / yellow / red / blue
- Headless Python systemd service (GPIO only)
- **Real capture** via shared ElaTool `readonly_capture` engine (PCSniff parity)
- **Automatic technology dispatch:** NTAG I²C Plus **or** FeliCa / NFC Forum Type 3
  (see [`docs/FELICA_AUTO_DISPATCH.md`](docs/FELICA_AUTO_DISPATCH.md))

**Not used:** LCD, touchscreen, Xorg, xinit, pygame, SDL, framebuffer, Waveshare.

Legacy Waveshare touch UI remains under `hwsniff.legacy` (`python -m hwsniff --legacy-ui`).

Config **must** include `hardware_profile: "v2"`. Alpha1 pin maps are rejected.

## GPIO map (v2)

| Function | Physical pin | BCM GPIO | Notes |
|----------|-------------:|---------:|--------|
| RESERVE  | 29 | 5  | unused |
| GND      | 30 | — | |
| STOP     | **31** | 6  | switch → GND, pull-up, OFF=1 ON=0 |
| DIP1     | **32** | 12 | switch → GND, pull-up, OFF=1 ON=0 |
| DIP2     | **33** | 13 | switch → GND, pull-up, OFF=1 ON=0 |
| GND      | 34 | — | |
| GREEN    | **35** | 19 | GPIO → 330 Ω → LED → GND, active-high |
| YELLOW   | **36** | 16 | same |
| RED      | **37** | 26 | same |
| BLUE     | **38** | 20 | WLAN heartbeat |
| GND      | 39 | — | |
| START    | **40** | 21 | switch → GND, pull-up, OFF=1 ON=0 |

```text
GPIO6  / pin 31 ── STOP  ── GND
GPIO12 / pin 32 ── DIP1 ── GND
GPIO13 / pin 33 ── DIP2 ── GND
GPIO19 / pin 35 ── 330Ω ── GREEN  ── GND
GPIO16 / pin 36 ── 330Ω ── YELLOW ── GND
GPIO26 / pin 37 ── 330Ω ── RED    ── GND
GPIO20 / pin 38 ── 330Ω ── BLUE   ── GND
GPIO21 / pin 40 ── START ── GND
```

## DIP modes

| DIP1 | DIP2 | Result |
|------|------|--------|
| OFF | OFF | MAIN |
| ON  | OFF | SWEETP |
| OFF | ON  | **UPLOAD** (WiFi FTP of export bundles) |
| ON  | ON  | ERROR3 |

Boot: MAIN (both OFF) or UPLOAD (DIP2 only). SWEETP/both-ON at boot → ERROR3.
DIP is monitored continuously; ERROR3 / mode changes recover without restart.

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

## ELATEC TWN4 over GPIO UART

Production reader path: **`/dev/serial0`** (stable alias → `ttyS0` / `ttyAMA*`), not a hard-coded `ttyS0`.

| Setting | Value |
|---------|--------|
| Baud | **9600** 8N1, no flow control |
| Host interface | COM1 (`HOSTSENSE` → **GND**) |
| Firmware | Simple Protocol (e.g. `TWN4_*_Simple_Protocol.bix`) |
| Config | `"reader.preferred_serial": "/dev/serial0"`, `"auto_detect": true` |

Pi firmware:

```text
# /boot/firmware/config.txt
enable_uart=1

# /boot/firmware/cmdline.txt — remove console=serial0,115200
```

**Port exclusivity:** `hwsniff.service` and any manual UART tool must not share the port.
Before manual tests (`tests/twn4_uart_test.py`, screen, minicom):

```bash
sudo systemctl stop hwsniff
```

If open fails with busy / exclusive error, the service (or another process) still holds the UART.

## Export bundles

After each successful tag capture, artifacts are packed into an uncompressed **`.tar`**
(`DDMMYYYY_HH_MM.tar`) under the primary root:

| Option | Default | Meaning |
|--------|---------|---------|
| `collector.export_bundle_root` | `/var/lib/hwsniff/export` | Authoritative primary output |
| `collector.export_bundle_mirror_root` | `/home/sniffer/exports` (example) | Optional identical copy; `null` = off |
| `collector.include_logs_in_bundle` | `false` (code default) | When `true`, pack `log_root` files under `logs/` |

Primary archive is written atomically (`.tmp` + rename). Mirror copy runs only after
primary success; mirror failures are logged and never delete the primary ZIP/tar.
Installer creates the mirror dir as `hwsniff:sniffer` mode `2775` (writable by service, readable by login user).

## WiFi upload mode (DIP2)

DIP2 ON (DIP1 OFF) uploads finished bundles from **`collector.export_bundle_root`**
only (not the mirror). WiFi association stays with NetworkManager; the app checks
interface + IP + default route, then FTP/FTPS.

State file: `/var/lib/hwsniff/upload-state.json` (survives reboot). Local files are
never deleted after upload. FTP password: set in `/etc/hwsniff/config.json` **on the Pi**
or via env `HWSNIFF_FTP_PASSWORD` — never commit secrets.

LED cues (upload mode owns G/Y/R/B): chase while transferring; green success;
yellow empty queue; blue = no WiFi; red = FTP error; Y/R = partial.

## Install / deploy

See **[deploy/README.md](deploy/README.md)**.

```powershell
cd tools\HWSniff\deploy
.\deploy-to-pi.ps1
```

On an already-installed appliance (pulls OpenVusion + syncs HWSniff **and**
ElaTool into `/opt/Sniff/_vendor/ElaTool`, reinstalls editable packages, restarts):

```bash
cd /opt/OpenVusion   # or your clone path
sudo bash tools/HWSniff/safe-update.sh --restart
# smoke must print CaptureProbe / hwsniff 2.1.x
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
