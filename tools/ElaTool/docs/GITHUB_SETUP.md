# GitHub repozitář

Oficiální repozitář projektu:

```text
https://github.com/H0nz4k/elaUIDtool
```

## První stažení

```bash
git clone https://github.com/H0nz4k/elaUIDtool.git
cd elaUIDtool
```

## Běžná práce

```bash
git pull
git status
git add <soubory>
git commit -m "feat: popis změny"
git push
```

## Vydání nové verze

Postup je popsán v `docs/VERSIONING.md`. Základní sekvence:

```bash
python scripts/release.py 0.1.3
python -m unittest discover -s tests -v
python scripts/check_version.py

git add -A
git commit -m "chore: release 0.1.3"
git tag -a v0.1.3 -m "ELATEC UID Tool v0.1.3"
git push origin main
git push origin v0.1.3
```

## Soubory, které se nepublikují

Do veřejného repozitáře nepatří:

- proprietární ELATEC Developer Pack,
- firmware `.bix` získaný od výrobce nebo klienta,
- interní databázové exporty a identifikátory klientů,
- proprietární PDF dokumentace,
- virtuální prostředí `.venv`,
- lokální výsledky v adresáři `results/`.
