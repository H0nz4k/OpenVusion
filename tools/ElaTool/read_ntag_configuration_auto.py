from __future__ import annotations

import importlib
import sys
from pathlib import Path


PORT = "COM6"


def find_package() -> tuple[str, Path]:
    """Najde lokální Python balíček obsahující ntag.py a protocol.py."""
    project_root = Path(__file__).resolve().parent

    candidates: list[Path] = []

    for ntag_path in project_root.rglob("ntag.py"):
        package_dir = ntag_path.parent

        if not (package_dir / "protocol.py").exists():
            continue

        if not (package_dir / "__init__.py").exists():
            continue

        candidates.append(package_dir)

    if not candidates:
        raise RuntimeError(
            "Nenašel jsem balíček obsahující současně ntag.py, protocol.py "
            "a __init__.py. Spusť skript z kořene projektu."
        )

    # Preferujeme nejbližší balíček ke kořeni projektu.
    package_dir = sorted(
        candidates,
        key=lambda path: len(path.relative_to(project_root).parts),
    )[0]

    package_parent = package_dir.parent
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

    return package_dir.name, package_dir


def main() -> None:
    package_name, package_dir = find_package()

    print(f"Nalezen balíček: {package_name}")
    print(f"Cesta:            {package_dir}")
    print(f"Otevírám čtečku:  {PORT}")

    ntag_module = importlib.import_module(f"{package_name}.ntag")
    protocol_module = importlib.import_module(f"{package_name}.protocol")

    NtagI2CPlus = ntag_module.NtagI2CPlus
    SimpleProtocolClient = protocol_module.SimpleProtocolClient

    with SimpleProtocolClient(PORT, timeout=2.0) as client:
        tag = client.search_tag()
        if tag is None:
            raise RuntimeError(
                "NFC tag nebyl nalezen. Přilož štítek ke čtečce."
            )

        uid = getattr(tag, "id_hex", None)
        tag_type = getattr(tag, "tag_type", None)
        id_bit_count = getattr(tag, "id_bit_count", None)

        if uid is not None:
            print(f"UID:      {uid}")
        if tag_type is not None:
            print(f"TagType:  0x{tag_type:02X}")
        if id_bit_count is not None:
            print(f"ID bits:  {id_bit_count}")

        ntag = NtagI2CPlus(client)

        version = ntag.get_version()
        print()
        print("GET_VERSION")
        print("-----------")
        print(version.raw.hex(" ").upper())

        print()
        print("NTAG configuration registers")
        print("============================")

        config = ntag.read_configuration_registers()

        for page, data in config.items():
            print(f"0x{page:02X}: {data.hex(' ').upper()}")

        print()
        print("Čtení dokončeno. Nebyl proveden žádný zápis do tagu.")


if __name__ == "__main__":
    main()
