from __future__ import annotations

import csv
import hashlib
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".hwsniff_write_probe"
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink(missing_ok=True)


def free_space_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    usage = os.statvfs(path) if hasattr(os, "statvfs") else None
    if usage is not None:
        return int(usage.f_bavail * usage.f_frsize)
    # Windows fallback for unit tests
    import shutil

    return int(shutil.disk_usage(path).free)


def create_capture_directory(capture_root: Path, uid: str | None) -> Path:
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    uid_part = (uid or "UNKNOWN").upper()
    directory = capture_root / day / f"{stamp}_{uid_part}"
    suffix = 1
    while directory.exists():
        directory = capture_root / day / f"{stamp}_{uid_part}_{suffix}"
        suffix += 1
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_index(
    data_root: Path,
    record: dict[str, Any],
) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    jsonl = data_root / "index.jsonl"
    with jsonl.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    csv_path = data_root / "index.csv"
    fieldnames = [
        "timestamp",
        "uid",
        "get_version",
        "finish_status",
        "directory",
        "duplicate",
        "application_sha256",
    ]
    exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({key: record.get(key, "") for key in fieldnames})


def index_contains_uid(data_root: Path, uid: str) -> bool:
    jsonl = data_root / "index.jsonl"
    if not jsonl.exists():
        return False
    target = uid.upper()
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(item.get("uid", "")).upper() == target:
            return True
    return False


def verify_artifacts(directory: Path, required: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in required:
        path = directory / name
        if not path.exists():
            raise FileNotFoundError(f"Missing artifact: {name}")
        # Re-open and hash
        hashes[name] = sha256_file(path)
    write_json(directory / "hashes.json", hashes)
    # Confirm hashes file itself
    _ = sha256_file(directory / "hashes.json")
    return hashes


def export_bundle_stamp(when: datetime | None = None) -> str:
    """Archive stamp: DDMMYYYY_HH_MM (e.g. 31072026_05_15)."""
    now = when or datetime.now()
    return now.strftime("%d%m%Y_%H_%M")


def resolve_export_tar_path(
    export_root: Path,
    *,
    when: datetime | None = None,
) -> Path:
    """Return /home/sniffer/capture/DDMMYYYY_HH_MM.tar (unique within the minute)."""
    root = Path(export_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = export_bundle_stamp(when)
    tar_path = root / f"{stamp}.tar"
    suffix = 1
    while tar_path.exists():
        tar_path = root / f"{stamp}_{suffix}.tar"
        suffix += 1
    return tar_path


def pack_capture_export(
    capture_directory: Path,
    *,
    export_root: Path | None = None,
    when: datetime | None = None,
    tar_path: Path | None = None,
) -> Path:
    """Pack every capture file into export_root/DDMMYYYY_HH_MM.tar."""
    capture_directory = Path(capture_directory)
    if not capture_directory.is_dir():
        raise FileNotFoundError(f"Capture directory missing: {capture_directory}")

    if tar_path is None:
        if export_root is None:
            raise ValueError("export_root or tar_path is required")
        tar_path = resolve_export_tar_path(export_root, when=when)
    else:
        tar_path = Path(tar_path)
        tar_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        path for path in capture_directory.rglob("*") if path.is_file()
    )
    if not files:
        raise FileNotFoundError(f"No files to pack in {capture_directory}")

    # Uncompressed .tar as requested (portable, easy to inspect on the Pi).
    with tarfile.open(tar_path, mode="w") as archive:
        for path in files:
            archive.add(path, arcname=path.name)

    with tar_path.open("rb") as handle:
        handle.read(1)
    return tar_path
