# PCSniff / TWN4 Capture Probe

Jednoduchý Windows diagnostický nástroj pro **read-only** ověření čtení ELATEC TWN4 a RFID/NFC tagu.

- bez Raspberry Pi, pygame, systemd, Xorg a HWSniff UI
- jeden proces, jeden COM port, jeden tag, jeden capture
- sdílí capture engine s HWSniff: `elatec_uid_tool.readonly_capture`
  (stejná sekvence, retry, persistence; HWSniff je jen UI/orchestrace)

## Instalace

PowerShell / CMD:

```bat
cd tools\PCSniff
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -U pip
pip install -e ..\ElaTool
pip install -e ".[dev]"
```

Git Bash:

```bash
cd tools/PCSniff
python -m venv .venv
source .venv/Scripts/activate
pip install -U pip
pip install -e ../ElaTool
pip install -e ".[dev]"
```

## Spuštění

PowerShell:

```powershell
py -m twn4_capture_probe --auto-port --raw-trace
# nebo
py -m twn4_capture_probe --port COM5 --raw-trace
```

Git Bash:

```bash
python -m twn4_capture_probe --auto-port --raw-trace
```

Pomocné skripty (vytvoří venv při prvním běhu):

- `run-windows.cmd`
- `run-windows.ps1`
- `run-git-bash.sh`

## CLI

| Parametr | Význam |
|----------|--------|
| `--port COM5` | Explicitní COM port |
| `--auto-port` | Najít jednu ELATEC TWN4 |
| `--output PATH` | Kořen výstupu (default `capture/windows_probe`) |
| `--raw-trace` | Ukládat TX/RX Simple Protocol hex |
| `--tag-timeout 60` | Timeout čekání na tag (s) |
| `--retry-count 3` | Retry na fázi |
| `--retry-delay-ms 150` | Prodleva mezi retry |
| `--session-seconds 2` | Délka session monitoringu |
| `--skip-eeprom` / `--skip-application` / `--skip-session` | Přeskočit fázi |
| `--verbose` | Více výpisů |

## Capture plán (read-only)

1. Reader handshake / version / device type
2. Čekání na první tag (`SearchTag` + RF wake)
3. Zamčení UID + 3× potvrzení stejného UID
4. Identifikace (`GET_VERSION`) — NTAG I²C Plus plán
5. EEPROM dump `0x00–0xE1` (chunked FAST_READ)
6. Application block `0x30–0x37` + page `0x00`
7. Session registry vzorkování (`0xEC–0xED`)
8. Verifikace UID / version / application
9. Uložení diagnostického balíčku a exit

Po prvním UID se **nečeká** na oddálení tagu a nepřijímají se další UID.

## Výstup

Pracovní adresář zůstává `*_UID-pending` po celou dobu capture. Přejmenování
na `*_UID-<uid>` probíhá až po zavření serial portu a raw traceru.

```
capture/windows_probe/
  2026-07-31_053900_UID-04AABBCC/
    summary.json
    events.jsonl
    raw_serial.jsonl          # jen s --raw-trace
    phases/*.json
    errors.json
    console.log
    environment.json
```

## Celkový status

- **SUCCESS** — povinné fáze OK, ostatní OK/SKIPPED
- **PARTIAL** — data/UID jsou, ale něco selhalo / unsupported
- **FAILED** — nelze otevřít reader, žádný tag, nebo žádná použitelná data

## Testy

```bash
cd tools/PCSniff
python -m unittest discover -s tests -v
```

## Ruční fyzický test

1. Připojit TWN4 k Windows.
2. Ověřit COM port ve Správci zařízení.
3. Vytvořit virtualenv (viz Instalace).
4. Spustit `python -m twn4_capture_probe --port COMx --raw-trace`.
5. Po `Čekám na tag...` přiložit tag.
6. Po `TAG DETECTED` nehýbat tagem ani čtečkou.
7. Počkat na `RESULT: ...` a cestu `Output: ...`.
8. Zabalit celý výstupní adresář do ZIP.
9. Porovnat fáze se statusem jiným než `ok`.
