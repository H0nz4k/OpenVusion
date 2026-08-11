# WaterFall 0.4.0 — validační stav

Datum: 2026-08-11

## PASS v build prostředí

- `python3 -m py_compile` pro `app/*.py`, `run_server.py` a tests;
- 6 unit testů:
  - RF narrow candidate;
  - RF wide/Wi-Fi-like shape;
  - channel labels;
  - BLE device registry merge;
  - BLE advertising report conversion;
  - PCAP filename sanitization/library;
- `node --check` pro oba JavaScript bundle soubory;
- UI bylo rozděleno na HTML + CSS + dva JS soubory bez změny funkcí;
- backend byl rozdělen na menší moduly (`core.py`, `routes.py`, `probe_discovery.py`) a znovu zkompilován/testován;
- mock HTTP smoke test:
  - `/api/health`;
  - `/api/capabilities`;
  - generování RF sweepů;
  - start/stop capture session;
  - vytvoření ZIP;
  - browser uložených sessions;
  - focused watch API + živé mock RSSI samples.

## Není fyzicky ověřeno v tomto prostředí

- reálný Raspberry Pi 3 runtime s BlueZ/Bleak;
- reálný `tshark` decode;
- reálný TWN4 + relay souběh s WaterFall 0.4.0;
- reálný OpenVusion RF Probe 0.7.0, dokud neprojde NCS build + flash + `test_usb.py`.

Tyto body nejsou označené jako PASS. Poslední fyzicky ověřený firmware donglu zůstává 0.6.1.
