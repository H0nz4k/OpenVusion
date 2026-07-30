from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrsImage:
    path: Path
    name: str


def find_prs_images(devpack_root: Path) -> list[PrsImage]:
    """Najde PRS Simple Protocol image v rozbaleném TWN4 Developer Packu."""
    if not devpack_root.exists():
        raise ValueError(f"Cesta neexistuje: {devpack_root}")
    if not devpack_root.is_dir():
        raise ValueError(f"Cesta není adresář: {devpack_root}")

    images: list[PrsImage] = []
    for path in devpack_root.rglob("*.bix"):
        if "PRS" in path.name.upper():
            images.append(PrsImage(path=path.resolve(), name=path.name))

    images.sort(key=lambda item: (item.name.upper(), str(item.path).upper()))
    return images


def find_programming_tools(devpack_root: Path) -> list[Path]:
    """Najde pravděpodobné programovací nástroje pro pozdější CLI integraci."""
    tools_root = devpack_root / "Tools"
    if not tools_root.exists():
        return []

    keywords = ("program", "flash", "boot", "image", "twn4")
    result: list[Path] = []
    for path in tools_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".exe", ".bat", ".cmd"):
            continue
        name = path.name.lower()
        if any(keyword in name for keyword in keywords):
            result.append(path.resolve())

    result.sort(key=lambda item: str(item).upper())
    return result
