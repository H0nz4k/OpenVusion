# OpenVusion HWSniff

HWSniff is a **headless read-only field capture appliance** for investigating NFC/electronic shelf label tags with an ELATEC TWN4 reader.

Current hardware target: **Raspberry Pi Zero 2 W**.

The original Waveshare 3.5" touchscreen/X11 implementation remains available as legacy code, but it is no longer the primary hardware profile.

## Current v2 hardware

- Raspberry Pi Zero 2 W
- ELATEC TWN4 over USB OTG
- 2 push buttons
- 2 DIP switches
- 4 LEDs
- no LCD / no touchscreen

Current field GPIO map:

| Function | Physical pin | BCM GPIO |
|---|---:|---:|
| START | 40 | GPIO21 |
| STOP | 31 | GPIO6 |
| DIP1 | 32 | GPIO12 |
| DIP2 | 33 | GPIO13 |
| GREEN | 35 | GPIO19 |
| YELLOW | 36 | GPIO16 |
| RED | 37 | GPIO26 |
| BLUE | 38 | GPIO20 |

See [docs/HARDWARE_V2.md](docs/HARDWARE_V2.md) for wiring, LED behavior, state logic, SweetP thresholds and physical-test lessons.

## Purpose

- offline field collection on SD card
- no keyboard/mouse/display required
- auto-detect ELATEC reader (no fixed `ttyACM0` assumption)
- reuse the same verified ElaTool read-only capture engine as PCSniff
- avoid protocol duplication in HWSniff
- preserve partial/raw evidence when a phase fails
- provide deterministic physical feedback with LEDs

## Main v2 workflow

```text
BOOT
  ↓
READY
  ↓ START
POSITIONING / SWEETP quality
  ↓ START when quality is acceptable
READ
  ↓
READ_COMPLETE
  ↓
SAVE
  ↓
READY
```

STOP performs cooperative cancellation; it does not hard-kill the process.

### READ progress

GREEN / YELLOW / RED form a six-step progress bar:

```text
1 UID confirm       -> GREEN blink
2 identification    -> GREEN solid
3 EEPROM            -> GREEN solid + YELLOW blink
4 application       -> GREEN + YELLOW solid
5 session           -> GREEN + YELLOW solid + RED blink
6 verification      -> GREEN + YELLOW + RED solid
```

After reader work completes, GREEN + YELLOW + RED blink together 5×. This tells the operator that the reader may be moved away from the tag. SAVE is indicated by YELLOW solid.

## Modes

Current hardware intent:

| DIP1 | DIP2 | Mode |
|---|---|---|
| OFF | OFF | MAIN |
| ON | OFF | SWEETP |
| OFF | ON | UPLOAD / Wi-Fi mode (planned) |
| ON | ON | invalid / ERROR3 |

The current software may still treat DIP2 as reserved until upload mode is implemented and tested.

## SWEETP

SWEETP is a live read-stability / position-quality metric. It is **not RF RSSI**.

Current field-oriented bands:

```text
75–100  GREEN
56–74   YELLOW
40–55   YELLOW/RED alternating (borderline)
0–39    RED
```

Current minimum quality for starting READ: `56`.

See [docs/SWEETP.md](docs/SWEETP.md).

## Known tag technology findings

HWSniff must not assume that every detected tag is NTAG/Type 2.

Physically verified reference path:

- NTAG I²C Plus 1K
- complete reader-info / UID / identification / EEPROM / application / session / verification capture

Field work on SOLUM ESL labels produced a different tag family:

- SOLUM model `EL026F3BYA`
- observed reader tag type `0x85`
- 64-bit identifiers
- UID confirmation works
- NTAG `GET_VERSION` / Type-2 `READ` do not behave like NTAG
- current working hypothesis: **FeliCa / NFC Forum Type 3**

This is recorded as a hypothesis until native FeliCa probing or ELATEC tag-type mapping confirms it.

See [docs/TAG_TECHNOLOGIES.md](docs/TAG_TECHNOLOGIES.md).

## Runtime directory

GPIO/lgpio runtime must use a writable current working directory.

A physical Pi test exposed failures when GPIO code was launched from read-only `/opt/Sniff`.

Use:

```text
/var/lib/hwsniff
```

Systemd should use:

```ini
WorkingDirectory=/var/lib/hwsniff
```

## Diagnostics

Typical manual diagnostics on Pi:

```bash
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --diagnostics
```

GPIO test:

```bash
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
```

Service:

```bash
sudo systemctl enable --now hwsniff
journalctl -u hwsniff -f
```

## Architecture

HWSniff is the physical appliance/orchestration layer.

The reader/protocol/capture implementation belongs in the shared ElaTool layer used by PCSniff and HWSniff.

```text
ElaTool shared read-only capture engine
        ├── PCSniff
        └── HWSniff v2
```

Do not create a second independent TWN4 protocol implementation inside HWSniff.

## Docs

- [docs/HARDWARE_V2.md](docs/HARDWARE_V2.md)
- [docs/TAG_TECHNOLOGIES.md](docs/TAG_TECHNOLOGIES.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/INSTALLATION.md](docs/INSTALLATION.md)
- [docs/READER_AUTODETECTION.md](docs/READER_AUTODETECTION.md)
- [docs/STORAGE_FORMAT.md](docs/STORAGE_FORMAT.md)
- [docs/FIELD_WORKFLOW.md](docs/FIELD_WORKFLOW.md)
- [docs/SWEETP.md](docs/SWEETP.md)
- [docs/TOUCH_UI.md](docs/TOUCH_UI.md) — legacy UI

## Development tests (PC)

```bash
cd tools/HWSniff
python -m venv .venv
.venv/Scripts/pip install -e ../ElaTool -e ".[dev]"
.venv/Scripts/python -m unittest discover -s tests -v
```
