# HWSniff v2 — hardware specification

HWSniff v2 is the current headless field appliance based on Raspberry Pi Zero 2 W and an ELATEC TWN4 reader.

The old Raspberry Pi + Waveshare/X11/touchscreen implementation is legacy-only.

## Target hardware

- Raspberry Pi Zero 2 W
- ELATEC TWN4 over USB OTG
- 2 push buttons
- 2 DIP switches
- 4 LEDs
- no LCD / no touchscreen

## GPIO map

| Function | Physical pin | BCM GPIO | Electrical behavior |
|---|---:|---:|---|
| START | 40 | GPIO21 | active-low, internal pull-up |
| STOP | 31 | GPIO6 | active-low, internal pull-up |
| DIP1 | 32 | GPIO12 | active-low, internal pull-up |
| DIP2 | 33 | GPIO13 | active-low, internal pull-up |
| GREEN LED | 35 | GPIO19 | active-high |
| YELLOW LED | 36 | GPIO16 | active-high |
| RED LED | 37 | GPIO26 | active-high |
| BLUE LED | 38 | GPIO20 | active-high |
| GND | 30 / 34 / 39 | — | common ground |

### START GPIO change found during physical testing

START was initially planned on physical pin 29 / GPIO5. On the real Raspberry Pi Zero 2 W assembly, STOP on GPIO6 worked but START on GPIO5 did not react. Re-mapping START to physical pin 40 / GPIO21 worked immediately.

Current v2 field wiring therefore uses **START = GPIO21 / physical pin 40**.

GPIO5 should not be assumed functional for START until the original board/wiring issue is investigated separately.

## Buttons

Use internal pull-ups:

```text
GPIO ── button ── GND
```

Logic:

- released = HIGH
- pressed = LOW

Current mapping:

```text
GPIO21 / pin 40 ── START ── GND
GPIO6  / pin 31 ── STOP  ── GND
```

Mechanical debounce is handled in software. A practical test value is approximately 100–200 ms for the current buttons.

## DIP switches

Use the same active-low wiring:

```text
GPIO12 / pin 32 ── DIP1 ── GND
GPIO13 / pin 33 ── DIP2 ── GND
```

Logic:

- OFF = HIGH
- ON = LOW

### Planned mode map

| DIP1 | DIP2 | Mode |
|---|---|---|
| OFF | OFF | MAIN |
| ON | OFF | SWEETP |
| OFF | ON | UPLOAD / Wi-Fi mode (planned) |
| ON | ON | ERROR3 / invalid combination |

The first v2 software implementation treated DIP2 as reserved and therefore as ERROR3 whenever ON. The current hardware/design intent is to assign DIP2 to an upload mode once that workflow is implemented and tested.

## LEDs

Each LED has its own series resistor. Recommended value: **330 Ω**.

```text
GPIO ── 330 Ω ── LED anode (+)
LED cathode (-) ── GND
```

Current mapping:

```text
GPIO19 / pin 35 ── GREEN
GPIO16 / pin 36 ── YELLOW
GPIO26 / pin 37 ── RED
GPIO20 / pin 38 ── BLUE
```

LEDs are active-high.

## Boot self-test

At application startup run two complete LED cycles:

```text
GREEN → YELLOW → RED → BLUE
```

Each LED is approximately 500 ms ON, then OFF.

The sequence confirms that the application is alive and every LED output works physically.

## Main status LEDs

### READY

```text
GREEN ON
YELLOW OFF
RED OFF
```

### ERROR1 — fatal internal error

```text
RED ON
```

ERROR1 means the running application detected a fatal condition. A process that never started cannot itself illuminate an error LED.

### ERROR2 — TWN4 missing

```text
GREEN + RED blink synchronously at 1 Hz
```

HWSniff repeatedly probes the reader and automatically recovers when the TWN4 is reconnected.

Reader loss behavior:

- READY → ERROR2
- SWEETP → stop polling safely → ERROR2
- POSITIONING → stop positioning → ERROR2
- READ → preserve valid collected data, close capture safely, then ERROR2
- SAVE → reader loss must not invalidate SAVE if reader access is no longer required

### ERROR3 — invalid DIP combination

RED repeats:

```text
ON 0.5 s
OFF 0.5 s
ON 0.5 s
OFF 0.5 s
ON 0.5 s
OFF 1.5 s
```

## WLAN LED

BLUE is independent of the main state machine.

- Wi-Fi connected with usable IP: short BLUE pulse every 3 seconds
- Wi-Fi disconnected: BLUE OFF

## SWEETP bands

SWEETP is not RF RSSI. It is an inferred communication-quality/stability score.

Current field-oriented thresholds:

| Score | LED | Meaning |
|---:|---|---|
| 75–100 | GREEN solid | good / ideal |
| 56–74 | YELLOW solid | usable |
| 40–55 | YELLOW / RED alternating | borderline |
| 0–39 | RED solid | poor |
| no tag | G/Y/R off | no target |

Recommended hysteresis: 3 points.

Current minimum score for starting READ: **56**.

## MAIN state flow

```text
READY
  ↓ START
POSITIONING
  ↓ START when SweetP >= 56
READ
  ↓
READ_COMPLETE
  ↓
SAVE
  ↓
READY
```

STOP performs cooperative cancellation, never a hard process kill.

## READ progress using 3 LEDs / 6 phases

During READ the GREEN/YELLOW/RED LEDs become a six-step progress display:

| Step | Capture phase | GREEN | YELLOW | RED |
|---:|---|---|---|---|
| 1/6 | UID confirm | blink | off | off |
| 2/6 | identification | solid | off | off |
| 3/6 | EEPROM | solid | blink | off |
| 4/6 | application | solid | solid | off |
| 5/6 | session | solid | solid | blink |
| 6/6 | verification | solid | solid | solid |

After the reader portion completes, GREEN + YELLOW + RED blink together 5× at about 500 ms cadence. This means the reader may be moved away from the ESL/tag.

SAVE is indicated by YELLOW solid. Successful SAVE returns to READY.

## USB OTG wiring note

For a homemade micro-USB OTG host cable, the micro-USB **ID pin must be tied to GND** so that the Pi Zero 2 W operates the data port in host mode.

Typical host wiring:

```text
micro-USB pin 1 VBUS → USB-A pin 1 VBUS
micro-USB pin 2 D-   → USB-A pin 2 D-
micro-USB pin 3 D+   → USB-A pin 3 D+
micro-USB pin 4 ID   → GND
micro-USB pin 5 GND  → USB-A pin 4 GND
```

## lgpio runtime directory lesson

Physical testing exposed this failure when GPIO code was launched with current working directory `/opt/Sniff`:

```text
lguGetWorkDir: can't set working directory (Permission denied)
xCreatePipe: Can't set permissions for /opt/Sniff/.lgd-nfy...
```

The runtime directory must be writable, preferably:

```text
/var/lib/hwsniff
```

Systemd should therefore use:

```ini
WorkingDirectory=/var/lib/hwsniff
```

CLI diagnostics/GPIO test must also normalize to a writable runtime directory and must not solve the problem by making all of `/opt/Sniff` writable.
