# Trigger Analysis

Read-only nástroj pro hledání **asociací** mezi RF operacemi a přechodem
session registrů NTAG I²C Plus 1K.

## Cíl

Pozorované stavy (referenční VUSION štítek):

```text
baseline:      NC_REG=0x19  NS_REG=0x01
intermediate:  NC_REG=0x7C  NS_REG=0x41
active:        NC_REG=0x7C  NS_REG=0x29
```

Typická sekvence:

```text
0x19/0x01 → 0x7C/0x41 → 0x7C/0x29 → 0x19/0x01
```

Cílem je zjistit, která RF operace nebo sekvence s přechodem **souvisí**,
nikoli definitivně prokázat kauzalitu v izolovaném RF poli.

Fyzický `--all` retest ukázal, že téměř všechny RF scénáře vykazují stejný
cyklus; nejsilnější pracovní závěr je **obecná asociace s RF aktivitou /
selectem**, nikoli unikátní magic command.

## Stavový model

| Stav | NC | NS | Poznámka |
|---|---|---|---|
| `baseline` | `0x19` | `0x01` | klid |
| `intermediate` | `0x7C` | `0x41` | mezistav před kanonickým active |
| `active` | `0x7C` | `0x29` | kanonický active |
| `other` | jiné | jiné | neznámé; **ne** „všechno s NC=0x7C“ |

Detekované cykly:

- `baseline → intermediate → active → baseline` — canonical active cycle
- `baseline → active → baseline` — canonical active cycle
- `baseline → intermediate → baseline` — **observed transitional cycle**
  (ne canonical active)

## Baseline model (first-sample)

Session read sám vyvolává non-baseline okno. Platné metody:

| Metoda | Význam | Povinná? |
|---|---|---|
| `baseline_observed` | jeden platný `0x19/0x01` | ano, stačí |
| `baseline_confirmed_after_return` | settle viděl non-baseline cyklus + `--guard-ms` | preferovaná |
| `baseline_stable_by_multiple_reads` | ≥2 consecutive baseline | **ne** |

`contaminated` pouze: aktivní/intermediate/unknown pre-trigger, nedokončený
cyklus, RF chyba před triggerem.

## Metriky opakování

| Pole | Význam |
|---|---|
| `first_nonbaseline_us` | vstup do non-baseline (i přes intermediate) |
| `first_transition_us` | alias `first_nonbaseline_us` (compat) |
| `intermediate_enter_us` | vstup do `0x7C/0x41` |
| `active_enter_us` | vstup do `0x7C/0x29` |
| `return_us` | návrat na baseline |
| `intermediate_duration_us` | intermediate → active (nebo → return) |
| `canonical_active_duration_us` | active → return |
| `total_nonbaseline_window_us` | first non-baseline → return |
| `active_window_us` | **compat alias** `total_nonbaseline_window_us` |
| `intermediate_observed` / `canonical_active_observed` | bool |
| `returned_to_baseline` | bool |
| `cycle_kind` | `canonical_active_cycle` / `transitional_cycle` / … |

## Scénáře

| ID | Trigger operace |
|---|---|
| `select-only` | `SearchTag` (je trigger, ne skrytá příprava) |
| `get-version` | `GET_VERSION 0x60` |
| `read-page-00` | `READ` stránky `0x00` |
| `read-application-block` | `FAST_READ 0x30–0x37` |
| `read-session` | `FAST_READ 0xEC–0xED` |
| `get-version-then-session` | GET_VERSION + session |
| `repeated-session-only` | první session read = t=0 |

SRAM se **nepoužívá**.

`SearchTag rf_duration_us` je **transport/API wall time** (často stovky ms),
nikoli čistá doba RF rámce.

## Agregace

- `transition_repetitions` — úplné non-baseline cykly (canonical nebo transitional)
- `canonical_active_repetitions` — výskyt `0x7C/0x29`
- `intermediate_repetitions` — výskyt `0x7C/0x41`
- `state_counts` — počty sample stavů (baseline / intermediate / active / other)

### Slovník závěrů (per-scenario)

| Stupeň | Význam |
|---|---|
| `observed association` | alespoň jeden úplný cyklus |
| `repeatable association` | cyklus ve většině clean executed opakování |
| `general RF association` | sdílený pattern se select-only a většinou ostatních scénářů |
| `inconclusive` | žádný úplný cyklus / chyby / kontaminace |

**Nepoužívat** `probable trigger` jen proto, že 3/3 běhy jednoho scénáře
ukázaly přechod, pokud stejný přechod ukazují i ostatní RF operace.

### Globální závěr

Pokud `select-only` i většina ostatních scénářů vykazují obdobný cyklus:

> Results are consistent with a general RF/select-associated host wake-up,
> not a command-specific trigger.

Formulováno jako asociace, ne potvrzená kauzalita.

## CLI

```bash
python -m elatec_uid_tool trigger-analysis --port COM6 --all --verbose

python -m elatec_uid_tool trigger-analysis \
  --port COM6 --scenario get-version --repetitions 3 --guard-ms 200 --verbose
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

- ELATEC RF pole zůstává aktivní; host MCU může reagovat autonomně.
- Session čtení pro settle/probe interferuje (`measurement_interference_possible`).
- Výsledky jsou asociační, ne kauzální důkaz.
