from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = ROOT / "src" / "elatec_uid_tool" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)
CHANGELOG_VERSION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.MULTILINE)


def main() -> int:
    init_text = INIT_FILE.read_text(encoding="utf-8")
    match = SEMVER_RE.search(init_text)
    if not match:
        raise SystemExit("Nelze najít platné __version__ v __init__.py")

    version = ".".join(match.groups())
    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    versions = CHANGELOG_VERSION_RE.findall(changelog_text)
    if not versions:
        raise SystemExit("CHANGELOG neobsahuje žádnou vydanou verzi.")

    latest = versions[0]
    if version != latest:
        raise SystemExit(
            f"Nesoulad verze: balíček={version}, poslední CHANGELOG={latest}"
        )

    print(f"Verze je konzistentní: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
