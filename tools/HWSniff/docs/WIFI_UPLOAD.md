# WiFi upload mode (DIP2)

## DIP map

| DIP1 | DIP2 | Mode |
|------|------|------|
| OFF | OFF | MAIN |
| ON | OFF | SWEETP |
| OFF | ON | **UPLOAD** |
| ON | ON | ERROR3 |

Boot may start directly in UPLOAD. While UPLOAD is active, START/capture is blocked.

## What gets uploaded

- Source: `collector.export_bundle_root` (default `/var/lib/hwsniff/export`)
- Files: completed `*.tar` and `*.zip` (ignore `.tmp` / `.part`)
- **Not** mirrored from `export_bundle_mirror_root`
- Local files are kept after successful upload
- Oldest first

## State

`/var/lib/hwsniff/upload-state.json` — statuses `pending` / `uploading` /
`uploaded` / `failed`. Atomic write. `uploading` after crash → `pending`.

## Config snippet (edit on the Pi only)

Do **not** commit real passwords. Example for `/etc/hwsniff/config.json`:

```json
"upload": {
  "enabled": true,
  "trigger_mode": 2,
  "source_root": "/var/lib/hwsniff/export",
  "state_file": "/var/lib/hwsniff/upload-state.json",
  "server": "ftp.altisima.cz",
  "port": 21,
  "username": "altisimaservis.cz",
  "password": "<DOPLNIT_LOKÁLNĚ>",
  "remote_dir": "/servis/osobni_slozky/hamouz/tag_exports/",
  "use_tls": false,
  "passive": true,
  "connect_timeout_seconds": 15,
  "rescan_interval_seconds": 10,
  "retry_delays_seconds": [5, 15, 30, 60]
}
```

Alternative: `export HWSNIFF_FTP_PASSWORD='...'` in the systemd unit drop-in
(`Environment=HWSNIFF_FTP_PASSWORD=...`) with file mode `0600`.

## WiFi

NetworkManager owns SSIDs/passwords. The app only verifies `wlan0` is up, has IPv4,
and a default route. FTP failures are separate from “no WiFi”.

## LEDs

| Situation | Pattern |
|-----------|---------|
| Active scan/transfer | G → Y → R chase (~200 ms), one LED at a time |
| All uploaded | Green solid ~2 s, then 3 short green blinks |
| Nothing to send | Yellow double blink ×3 |
| No WiFi | Blue triple blink + pause (loops) |
| FTP/auth/dir error | Red triple blink + pause (loops while retrying) |
| Partial success | Yellow/red alternate ×3, then retry |

## FTP transfer

Remote filename is `<stem>_<sha256-12><suffix>` so a rewritten local bundle with the
same basename uploads as a new object without silently overwriting a different remote size.

Upload as `<remote>.part`, then rename to final name. If rename already happened but
local state missed it, matching remote size recovers as uploaded. Differing remote size
is logged as a collision (`failed` / retry) — never overwritten quietly.
