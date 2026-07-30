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

## Baseline model (first-sample)

Fyzický `--all` test ukázal, že **session read sám vyvolává** přechod
`baseline → active (~50–120 ms) → baseline (~1,1 s)`. Požadavek na více
po sobě jdoucích baseline vzorků proto není na tomto hardware splnitelný.

Platné metody baseline (pole `baseline_method`):

| Metoda | Význam | Povinná pro scénář? |
|---|---|---|
| `baseline_observed` | jeden platný vzorek `0x19/0x01` | ano, stačí |
| `baseline_confirmed_after_return` | settle viděl `baseline → active → baseline` (`completed_active_cycle`) + `--guard-ms` | preferovaná |
| `baseline_stable_by_multiple_reads` | ≥2 consecutive baseline reads | **ne** — pouze volitelná anotace |

Jeden baseline vzorek **není** automaticky `contaminated` ani `inconclusive`.

### Contaminated pouze když

- pre-trigger stav je aktivní `0x7C/0x29`;
- stav je neznámý;
- probíhá neukončený aktivní cyklus na konci settle;
- RF chyba před trigger operací.

## Scénáře

| ID | Trigger operace (`rf_operation`) |
|---|---|
| `select-only` | `SearchTag` (reselect **je** trigger, ne skrytá příprava) |
| `get-version` | `GET_VERSION 0x60` |
| `read-page-00` | `READ` od stránky `0x00` |
| `read-application-block` | `FAST_READ 0x30–0x37` |
| `read-session` | `FAST_READ 0xEC–0xED` |
| `get-version-then-session` | GET_VERSION + session read |
| `repeated-session-only` | první session read = trigger t=0; další = observation |

SRAM se **nepoužívá**.

## Průběh scénáře

1. Settle (`--settle-ms`): first-sample baseline; preferuj completed cycle + `--guard-ms`.
2. Přípravný reselect (`SearchTag`) — **kromě** `select-only`.
3. Maximálně **jeden** pre-trigger session read (přeskočen u `select-only`,
   `read-session`, `repeated-session-only`). Zaznamenán jako
   `measurement_interference_possible=true`.
4. Provedení trigger operace (`trigger_executed=true`) s `rf_duration_us`.
5. Post-op session sample (`post_op_hex`, pokud relevantní).
6. Monitoring session po `duration` s intervalem `interval-ms` → `samples`,
   `first_transition_us`, `return_us`, `transition_count`.
7. Opakování (`repetitions`).

Pokud `trigger_executed=false`, report uvádí explicitní důvod a opakování
**nevstupuje** do trigger statistik.

## Metadata výsledku (schema 2)

Klíčová pole opakování:

- `measurement_interference_possible`
- `baseline_method`
- `baseline_sample_count`
- `pre_trigger_state`
- `trigger_executed`
- `rf_duration_us`, `post_op_hex`, `samples`
- `first_transition_us`, `return_us`, `transition_count`

## Stupně závěru

| Stupeň | Význam |
|---|---|
| `observed association` | alespoň jedno **executed** opakování ukázalo přechod po akci |
| `repeatable association` | přechod ve většině čistých executed opakování |
| `probable trigger` | silná opakovatelnost + čistá baseline, stále bez izolovaného RF |
| `inconclusive` | žádné executed, kontaminace, chyby, chybějící návrat |

**Nepoužívat** `confirmed trigger` bez skutečně izolovaného RF pole.

## CLI

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose

python -m elatec_uid_tool trigger-analysis \
  --port COM6 --scenario get-version --repetitions 3 --verbose
```

Parametry: `--scenario`, `--all`, `--duration` (2), `--interval-ms` (50),
`--settle-ms` (1500), `--guard-ms` (200), `--repetitions` (3),
`--output-dir`, `--verbose`.

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
- Session čtení pro settle/probe samo interferuje (`measurement_interference_possible`).
- Předchozí scénář může kontaminovat následující (proto settle + reselect).
- Výsledky jsou asociační, ne kauzální důkaz.
