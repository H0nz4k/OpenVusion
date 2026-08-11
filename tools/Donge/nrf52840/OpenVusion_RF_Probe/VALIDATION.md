# OpenVusion RF Probe 0.7.0 — validační stav

Datum: 2026-08-11

## PASS v dostupném prostředí

- Python helper skripty projdou `py_compile`;
- `python3 verify_build.py --source-only` PASS;
- source-only verifier potvrdil:
  - `FW_NAME` 0.7.0;
  - WATCH příkazy;
  - RSSI MODE příkazy;
  - STEP příkazy;
  - focused `RSSI,...` output;
  - žádnou skutečnou RF TXEN operaci v C zdroji.

## Čeká na fyzický acceptance test

V tomto prostředí není Nordic NCS / Zephyr toolchain, proto zde nebylo možné
udělat skutečný `west build` ani flash.

Na uživatelském NCS 3.4.0 stroji je závazný postup:

```powershell
.\build_clean.ps1
```

Po flashi na Raspberry Pi:

```bash
python3 test_usb.py
```

Teprve po obou PASS bude 0.7.0 označena jako fyzicky ověřená.

Poslední fyzicky ověřený fallback je 0.6.1.
