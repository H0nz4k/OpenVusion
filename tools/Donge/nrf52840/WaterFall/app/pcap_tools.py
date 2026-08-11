from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class TsharkInspector:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tshark = shutil.which("tshark")
        self.capinfos = shutil.which("capinfos")

    @property
    def available(self) -> bool:
        return bool(self.tshark)

    @staticmethod
    def clean_name(name: str) -> str:
        base = Path(name).name
        cleaned = SAFE_NAME.sub("_", base).strip("._")
        if not cleaned:
            cleaned = "capture.pcapng"
        return cleaned[:160]

    def save_upload(self, filename: str, data: bytes) -> Path:
        name = self.clean_name(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in {".pcap", ".pcapng", ".cap"}:
            raise ValueError("Povolené jsou pouze .pcap, .pcapng nebo .cap")
        path = self.directory / name
        if path.exists():
            stem = path.stem
            suffix = path.suffix
            i = 2
            while (self.directory / f"{stem}_{i}{suffix}").exists():
                i += 1
            path = self.directory / f"{stem}_{i}{suffix}"
        path.write_bytes(data)
        return path

    def list_files(self) -> list[dict]:
        rows = []
        for p in sorted(self.directory.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix.lower() in {".pcap", ".pcapng", ".cap"}:
                rows.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                })
        return rows

    def resolve(self, filename: str) -> Path:
        name = self.clean_name(filename)
        path = (self.directory / name).resolve()
        root = self.directory.resolve()
        if root not in path.parents:
            raise ValueError("Neplatná cesta")
        if not path.exists():
            raise FileNotFoundError(name)
        return path

    def summary(self, filename: str, limit: int = 500, display_filter: str = "") -> list[dict]:
        if not self.tshark:
            raise RuntimeError("tshark není nainstalován")
        path = self.resolve(filename)
        limit = max(1, min(int(limit), 5000))
        cmd = [
            self.tshark, "-r", str(path), "-n", "-T", "fields",
            "-E", "separator=\\t", "-E", "quote=n", "-E", "occurrence=f",
            "-e", "frame.number",
            "-e", "frame.time_epoch",
            "-e", "frame.len",
            "-e", "_ws.col.Protocol",
            "-e", "_ws.col.Source",
            "-e", "_ws.col.Destination",
            "-e", "_ws.col.Info",
        ]
        if display_filter.strip():
            cmd.extend(["-Y", display_filter.strip()])
        cmd.extend(["-c", str(limit)])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "tshark selhal")
        rows = []
        for line in proc.stdout.splitlines():
            cols = line.split("\t")
            cols += [""] * (7 - len(cols))
            rows.append({
                "number": int(cols[0]) if cols[0].isdigit() else cols[0],
                "time_epoch": cols[1],
                "length": int(cols[2]) if cols[2].isdigit() else cols[2],
                "protocol": cols[3],
                "source": cols[4],
                "destination": cols[5],
                "info": cols[6],
            })
        return rows

    def detail(self, filename: str, frame_number: int) -> dict:
        if not self.tshark:
            raise RuntimeError("tshark není nainstalován")
        path = self.resolve(filename)
        n = max(1, int(frame_number))
        cmd = [
            self.tshark, "-r", str(path), "-n",
            "-Y", f"frame.number == {n}", "-V", "-x",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "tshark selhal")
        return {"number": n, "text": proc.stdout}
