# Field Workflow (one-shot START)

1. Power on the device.
2. Wait until screen shows **READY** / **READER READY**.
3. Optional: tap **SWEETP** to find a stable reader pose (no captures written).
4. Tap **START**.
5. Present **one** VUSION tag and keep it still.
6. UI shows phases: identifikace → EEPROM → application block → session → ověření → ukládání.
7. Capture ends with **HOTOVO**, **HOTOVO S CHYBAMI**, or **SELHALO**.
8. HWSniff does **not** automatically wait for another tag.
9. Tap **NOVÝ ŠTÍTEK** (or START from READY via ZPĚT) for the next tag.
10. Optionally tap **DETAIL** for per-phase status and paths.
11. Tap **SHUTDOWN** only from READY.

Each successful/partial capture also packs artifacts to the primary export root:

`/var/lib/hwsniff/export/DDMMYYYY_HH_MM.tar`

Optional identical mirror (Pi default): `/home/sniffer/exports/` (same filename).
With `include_logs_in_bundle: true`, application logs from `log_root` are stored
inside the archive under `logs/`.

Read-only only — never write to tags. SweetP is a positioning aid only;
see [SWEETP.md](SWEETP.md).

GPIO UART: prefer `/dev/serial0` @ 9600 8N1. Stop `hwsniff.service` before any
manual serial test so the port is free.
