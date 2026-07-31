# Reader Autodetection

User never sets COM/`tty` manually.

## Algorithm

1. Enumerate serial ports (`pyserial` `list_ports.comports()`).
2. Score candidates using:
   - USB VID `09D8` (ELATEC) when present in metadata;
   - product/manufacturer strings containing `ELATEC` / `TWN4`;
   - device node patterns `/dev/ttyACM*`, `/dev/ttyUSB*`;
   - optional preferred serial from config;
   - optional stable alias `/dev/hwsniff-reader` (not required).
3. For each high-score candidate, open briefly and run **read-only handshake**
   (`SimpleProtocolClient` open + no-op / SearchTag with short timeout).
4. Outcomes:
   - 0 verified → `READER_MISSING`
   - 1 verified → `READER READY`
   - >1 verified → `MULTIPLE READERS` (touch pick)

## When it runs

- boot / INITIALIZING
- START press
- disconnect recovery
- idle periodic scan
- after RF/serial failure if reconnect needed

## Physical discovery commands

```bash
lsusb
udevadm info -a -n /dev/ttyACM0
python -m serial.tools.list_ports -v
```

Do **not** invent VID/PID in udev rules. Parameterize from real `lsusb` output.

## Port changes

`/dev/ttyACM0` → `/dev/ttyACM1` after replug is handled by re-scan; no reboot.
