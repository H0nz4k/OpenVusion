import argparse
import json
from pathlib import Path

from elatec_uid_tool.ntag import NtagDump


def load_dump(path: Path) -> NtagDump:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pages = {int(page): bytes.fromhex(value) for page, value in raw["pages"].items()}
    return NtagDump(
        uid=raw["uid"],
        version=bytes.fromhex(raw["get_version"]),
        start_page=int(raw["range"]["start_page"]),
        end_page=int(raw["range"]["end_page"]),
        pages=pages,
        created_at=raw["created_at"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze an existing NTAG JSON dump.")
    parser.add_argument("dump_json", type=Path)
    args = parser.parse_args()

    dump = load_dump(args.dump_json)
    analysis = dump.analyze()
    print(analysis.to_text())

    stem = f"{args.dump_json.stem}-analysis"
    paths = analysis.save(args.dump_json.parent, stem=stem)

    print("Saved:")
    for kind, path in paths.items():
        print(f"  {kind.upper():4s}: {path.resolve()}")


if __name__ == "__main__":
    main()
