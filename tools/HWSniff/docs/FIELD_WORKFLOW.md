# Field Workflow

1. Power on the device.
2. Wait until screen shows **READY** / **READER READY**.
3. Optional: tap **SWEETP** to find a stable reader pose (no captures written).
4. Tap **START**.
5. Present a VUSION tag (or leave one already on the reader — START wakes it).
6. Wait for **CAPTURE OK** (green). Capture writes UID, GET_VERSION, application
   block, session registers, and full EEPROM dump.
7. Remove the tag when prompted (**Oddalte štítek**).
8. Present the next tag.
9. Tap **STOP** when finished (finishes in-flight capture first).
10. Optionally tap **SHUTDOWN** and confirm.
11. Export with `/opt/Sniff/scripts/export-data.sh /media/usb`.

Read-only only — never write to tags. SweetP is a positioning aid only;
see [SWEETP.md](SWEETP.md).
