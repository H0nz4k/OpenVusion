# Verzování a release proces

Projekt používá **Semantic Versioning** ve tvaru:

```text
MAJOR.MINOR.PATCH
```

Aktuálně je projekt před stabilní verzí 1.0.0. Pravidla v řadě `0.x.y`:

- `PATCH` – opravy, malé kompatibilní funkce, dokumentace a UX změny,
- `MINOR` – větší funkční celek, nový backend nebo změna CLI, která může vyžadovat úpravu použití,
- `MAJOR` – stabilní veřejné rozhraní od verze 1.0.0 a následné nekompatibilní změny.

## Git větve

- `main` musí obsahovat funkční a otestovaný stav,
- vývojové větve mají tvar `feature/...`, `fix/...`, `docs/...` nebo `refactor/...`,
- vydaná verze má anotovaný tag `vX.Y.Z`.

## Commit zprávy

Používáme Conventional Commits:

```text
feat: add multi-card consensus
fix: handle COM port already in use
docs: document PRS firmware workflow
refactor: separate transport from protocol parser
test: add non-byte-aligned UID cases
chore: release 0.1.3
```

Význam hlavních prefixů:

- `feat` – nová funkce,
- `fix` – oprava chyby,
- `docs` – pouze dokumentace,
- `test` – testy,
- `refactor` – změna interní struktury bez nové funkce,
- `chore` – údržba, build nebo release.

## CHANGELOG

Každá uživatelsky významná změna se nejdříve zapíše pod:

```markdown
## [Unreleased]
```

Používají se sekce:

```text
Added
Changed
Deprecated
Removed
Fixed
Security
```

## Vytvoření nové verze

1. Zkontroluj čistý pracovní strom:

```bash
git status
```

2. Doplň změny do `CHANGELOG.md` pod `Unreleased`.

3. Spusť release helper:

```bash
python scripts/release.py 0.1.3
```

Skript:

- ověří formát a pořadí verze,
- aktualizuje `src/elatec_uid_tool/__init__.py`,
- přesune obsah `Unreleased` do nové datované sekce.

4. Spusť kontroly:

```bash
python -m unittest discover -s tests -v
python scripts/check_version.py
```

5. Prohlédni diff a vytvoř release commit:

```bash
git add src/elatec_uid_tool/__init__.py CHANGELOG.md
git commit -m "chore: release 0.1.3"
```

6. Vytvoř anotovaný tag:

```bash
git tag -a v0.1.3 -m "ELATEC UID Tool v0.1.3"
```

7. Pushni commit i tag:

```bash
git push origin main
git push origin v0.1.3
```

## Jediný zdroj verze

Verze je definována pouze zde:

```text
src/elatec_uid_tool/__init__.py
```

`pyproject.toml` ji načítá dynamicky přes setuptools. Verze se tedy nesmí ručně duplikovat na více místech.
