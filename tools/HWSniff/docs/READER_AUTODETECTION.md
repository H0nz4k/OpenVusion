# Reader Autodetection

## Algorithm

1. Enumerate serial ports (`pyserial` `list_ports.comports()`).
2. Always consider filesystem aliases when present:
   - `/dev/serial0` (Pi GPIO UART — preferred production path)
   - `/dev/hwsniff-reader` (optional udev alias)
3. Score candidates using:
   - USB VID `09D8` (ELATEC) when present in metadata;
   - product/manufacturer strings containing `ELATEC` / `TWN4`;
   - device node patterns `/dev/ttyACM*`, `/dev/ttyUSB*`;
   - GPIO UART nodes `/dev/serial0`, `ttyS0`, `ttyAMA*`;
   - `reader.preferred_serial` — USB serial number **or** device path
     (e.g. `/dev/serial0`).
4. For each high-score candidate, open briefly and run **read-only handshake**
   (`SimpleProtocolClient` @ **9600** 8N1 + SearchTag with short timeout).
   On Linux the open uses exclusive mode when available — a busy port means
   another process (usually `hwsniff.service`) already holds UART.
5. Selection (`pick_reader`):
   - Prefer a **verified** candidate matching `preferred_serial`.
   - If preferred is missing/unverified and `auto_detect` is true → pick the
     single verified reader (fallback).
   - If preferred fails and several others verify → do not guess (`no_reader`).
   - If `auto_detect` is false and preferred fails → `no_reader`.

## Production config (Pi Zero GPIO UART)

```json
"reader": {
  "auto_detect": true,
  "preferred_serial": "/dev/serial0"
}
```

Hardware prerequisites:

- `/boot/firmware/config.txt`: `enable_uart=1`
- Remove `console=serial0,115200` from `/boot/firmware/cmdline.txt`
- ELATEC `HOSTSENSE` → GND (COM1)
- Simple Protocol firmware @ 9600 8N1

**Before manual UART tests** stop the service so the port is free:

```bash
sudo systemctl stop hwsniff
```

## When it runs

- boot / INITIALIZING
- START press
- disconnect recovery
- idle periodic scan
- after RF/serial failure if reconnect needed

## Physical discovery commands

```bash
ls -l /dev/serial0
python3 -m serial.tools.list_ports -v
# Manual Simple Protocol check (service must be stopped):
#   0004FF\r → version,  0500FF\r → tag UID
```

Do **not** invent VID/PID in udev rules. Parameterize from real `lsusb` output
when using USB ACM instead of GPIO UART.

## Port changes

USB `/dev/ttyACM0` → `/dev/ttyACM1` after replug is handled by re-scan; no reboot.
GPIO UART should keep using the `/dev/serial0` alias across boots.
