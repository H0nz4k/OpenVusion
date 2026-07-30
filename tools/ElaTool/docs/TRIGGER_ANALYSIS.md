# Trigger Analysis

Read-only nástroj pro hledání **asociací** mezi RF operacemi a přechodem
session registrů NTAG I²C Plus 1K.

## Cíl

Pozorované stavy (referenční VUSION štítek):

```text
baseline: NC_REG=0x19  NS_REG=0x01
active:   NC_REG=0x7C  NS_REG=0x29
```

Cílem je zjistit, která RF operace nebo sekvence s přechodem **souvisí**,
nikoli definitivně prokázat kauzalitu v izolovaném RF poli.

## Scénáře

| ID | RF akce před monitoringem |
|---|---|
| `select-only` | pouze SearchTag / reselect |
| `get-version` | `GET_VERSION 0x60` |
| `read-page-00` | `READ` od stránky `0x00` |
| `read-application-block` | `FAST_READ 0x30–0x37` |
| `read-session` | `FAST_READ 0xEC–0xED` |
| `get-version-then-session` | GET_VERSION + session read |
| `repeated-session-only` | opakované session reads po dobu duration |

SRAM se **nepoužívá**.

## Průběh scénáře

1. Best-effort settle: čekání na baseline (`settle-ms`).
2. Reselect (`SearchTag`).
3. Baseline sample(s); pokud nestabilní → `contaminated` / `inconclusive`.
4. Provedení RF akce scénáře (s měřením délky).
5. Okamžitý session sample.
6. Monitoring session po `duration` s intervalem `interval-ms`.
7. Výpočet: čas prvního přechodu, návrat, délka aktivního okna, počet přechodů.
8. Opakování (`repetitions`).

## Stupně závěru

| Stupeň | Význam |
|---|---|
| `observed association` | alespoň jedno opakování ukázalo přechod po akci |
| `repeatable association` | přechod ve většině nekontaminovaných opakování |
| `probable trigger` | silná opakovatelnost + čistá baseline, stále bez izolovaného RF |
| `inconclusive` | kontaminace, chyby, chybějící návrat nebo nestabilní baseline |

**Nepoužívat** `confirmed trigger` bez skutečně izolovaného RF pole.

## CLI

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose

python -m elatec_uid_tool trigger-analysis \
  --port COM6 --scenario get-version --repetitions 3 --verbose
```

Parametry: `--scenario`, `--all`, `--duration` (2), `--interval-ms` (50),
`--settle-ms` (1500), `--repetitions` (3), `--output-dir`, `--verbose`.

## Výstupy

```text
captures/trigger-analysis/<timestamp>_<UID>/
  metadata.json
  timeline.jsonl
  scenarios.csv
  report.txt
  errors.jsonl
```

## Omezení izolace

- ELATEC RF pole zůstává aktivní; host MCU štítku může reagovat autonomně.
- Předchozí scénář může kontaminovat následující (proto settle + reselect).
- Session čtení samotné může být součástí triggeru (`read-session`).
- Výsledky jsou asociační, ne kauzální důkaz.
