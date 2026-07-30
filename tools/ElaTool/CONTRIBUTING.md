# Přispívání do projektu

## Lokální příprava

```bash
py -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e .
```

## Testy

```bash
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python scripts/check_version.py
```

## Pravidla změn

- Jedna věcná změna na jeden commit.
- Používej Conventional Commits.
- Nová funkce nebo oprava musí mít test, pokud je rozumně testovatelná.
- Uživatelsky významné změny zapisuj do `CHANGELOG.md` pod `Unreleased`.
- Do repozitáře nepatří `.venv`, výsledky měření, produkční firmware klienta ani neveřejné ELATEC Developer Pack soubory.
- Proprietární PDF dokumentace ELATEC se do repozitáře nevkládá; dokumentace projektu na ni může pouze odkazovat názvem a revizí.
