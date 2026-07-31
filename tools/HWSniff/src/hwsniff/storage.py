from __future__ import annotations

from pathlib import Path

from elatec_uid_tool.field_collector import ensure_writable_dir, free_space_bytes


def prepare_storage(data_root: Path, capture_root: Path, log_root: Path) -> None:
    for path in (data_root, capture_root, log_root):
        ensure_writable_dir(Path(path))


def storage_status(
    data_root: Path,
    *,
    minimum_free_mb: int,
) -> tuple[bool, str, int]:
    free = free_space_bytes(Path(data_root))
    free_gb = free / (1024 ** 3)
    ok = free >= minimum_free_mb * 1024 * 1024
    text = f"Storage: {free_gb:.1f} GB free"
    if not ok:
        text = f"STORAGE FULL ({free_gb:.1f} GB free)"
    return ok, text, free
