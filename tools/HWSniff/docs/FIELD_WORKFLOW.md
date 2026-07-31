# Field Workflow

1. Power on the device.
2. Wait until screen shows **READY** / **READER READY**.
3. Optional: tap **SWEETP** to find a stable reader pose (no captures written).
4. Tap **START**.
5. Present a VUSION tag to the reader.
6. Wait for **CAPTURE OK** (green).
7. Remove the tag when prompted.
8. Present the next tag.
9. Tap **STOP** when finished (finishes in-flight capture first).
10. Optionally tap **SHUTDOWN** and confirm.
11. Export with `/opt/Sniff/scripts/export-data.sh /media/usb`.

Read-only only — never write to tags. SweetP is a positioning aid only;
see [SWEETP.md](SWEETP.md).
