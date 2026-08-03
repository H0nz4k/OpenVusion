#!/usr/bin/env python3
"""Build a self-contained HWSniff GPIO deploy tarball/zip for Raspberry Pi.

Run from any machine (Windows/macOS/Linux):

    python tools/HWSniff/deploy/pack_gpio_bundle.py

Output: tools/HWSniff/deploy/dist/hwsniff-gpio-<version>-<date>.tar.gz
        (+ .zip on Windows for convenience)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import tarfile
import zipfile
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "captures",
    "dist",
    "_staging",
    "build",
    "egg-info",
    "node_modules",
    ".cursor",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".egg-info"}
SKIP_NAME_PARTS = {".egg-info"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts:
        if part in SKIP_DIR_NAMES:
            return True
        if part.endswith(".egg-info"):
            return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    return False


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if should_skip(item, src):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_tar(src_dir: Path, out_path: Path) -> None:
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(src_dir, arcname=src_dir.name)


def make_zip(src_dir: Path, out_path: Path) -> None:
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in src_dir.rglob("*"):
            if item.is_file():
                zf.write(item, arcname=str(Path(src_dir.name) / item.relative_to(src_dir)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack HWSniff GPIO bundle for Pi")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
        help="Output directory for archives",
    )
    parser.add_argument("--zip", action="store_true", help="Also write .zip")
    args = parser.parse_args()

    root = repo_root()
    hwsniff = root / "tools" / "HWSniff"
    elatool = root / "tools" / "ElaTool"
    if not hwsniff.is_dir() or not elatool.is_dir():
        raise SystemExit(f"Expected tools/HWSniff and tools/ElaTool under {root}")

    version = "2.0.0"
    stamp = dt.datetime.now().strftime("%Y%m%d")
    name = f"hwsniff-gpio-{version}-{stamp}"
    staging = args.out_dir / "_staging" / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    copy_tree(hwsniff, staging / "tools" / "HWSniff")
    copy_tree(elatool, staging / "tools" / "ElaTool")

    # Top-level installer entry (same script as in deploy/)
    install_src = hwsniff / "deploy" / "install-on-pi.sh"
    shutil.copy2(install_src, staging / "install-on-pi.sh")
    # On Windows, ensure LF line endings for the shell script
    text = (staging / "install-on-pi.sh").read_bytes().replace(b"\r\n", b"\n")
    (staging / "install-on-pi.sh").write_bytes(text)

    readme = hwsniff / "deploy" / "README.md"
    if readme.exists():
        shutil.copy2(readme, staging / "README.md")

    (staging / "VERSION").write_text(
        f"hwsniff-gpio {version}\nbuilt={stamp}\nsource=OpenVusion\n",
        encoding="utf-8",
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = args.out_dir / f"{name}.tar.gz"
    make_tar(staging, tar_path)
    outputs = [tar_path]

    zip_path = args.out_dir / f"{name}.zip"
    make_zip(staging, zip_path)
    outputs.append(zip_path)

    sha_path = args.out_dir / f"{name}.sha256"
    lines = [f"{file_sha256(p)}  {p.name}" for p in outputs]
    sha_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    staging_root = staging.parent
    try:
        shutil.rmtree(staging_root)
    except OSError:
        pass

    print("Packed:")
    for p in outputs:
        print(f"  {p}  ({p.stat().st_size // 1024} KiB)")
    print(f"  {sha_path}")
    print()
    print("Copy to Pi, then:")
    print(f"  tar -xzf {tar_path.name}")
    print(f"  cd {name}")
    print("  sudo bash install-on-pi.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
