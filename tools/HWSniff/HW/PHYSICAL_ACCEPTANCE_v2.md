# HWSniff v2 — fyzický akceptační checklist (Pi Zero 2 W)

Unit testy nestačí. Ověř na hardwaru:

| # | Krok | Očekávání |
|---|------|-----------|
| A | boot | LED self-test 2× G→Y→R→B |
| B | TWN4 unplugged | ERROR2 (GREEN+RED 1 Hz) |
| C | plug TWN4 | READY bez restartu služby |
| D | Wi-Fi connected | BLUE heartbeat ~1× / 3 s |
| E | DIP1 ON | SWEETP |
| F | SweetP pohyb readeru | G / Y / YR / R pásma |
| G | DIP1 OFF | READY |
| H | START | POSITIONING |
| I | score ≥ 56 | GREEN nebo YELLOW |
| J | START | READ |
| K | READ | 6-step LED progress bar |
| L | reader complete | G+Y+R společně 5× |
| M | oddálit reader | po L |
| N | SAVE | YELLOW solid |
| O | SAVE OK | READY green |
| P | dataset | `captures/YYYY-MM-DD_HHMMSS_UID-…/` |
| Q | obsah | UID, identification, EEPROM, application, session, verification |
| R | STOP během positioning | cancel → READY |
| S | STOP během EEPROM | cancel / PARTIAL → READY |
| T | DIP2 ON | ERROR3 (RED 3× + pauza); OFF → recovery |

## Deploy příkaz

```powershell
cd tools\HWSniff\deploy
.\deploy-to-pi.ps1 -Mode Full
```

```bash
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --diagnostics
cd /var/lib/hwsniff
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
sudo systemctl restart hwsniff
journalctl -u hwsniff -f
```
