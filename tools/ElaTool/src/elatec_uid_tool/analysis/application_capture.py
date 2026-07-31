from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

from .. import __version__
from ..capture.models import safe_ascii_preview
from ..capture.writer import create_capture_dir
from ..ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_SIZE_BYTES,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from ..protocol import ElatecError, SerialCommunicationError, SimpleProtocolClient
from .application_block import analyze_application_block
from .dump_loaders import pages_to_block

FULL_DUMP_START_PAGE = 0x00
FULL_DUMP_END_PAGE = 0xE1
FULL_DUMP_CHUNK_PAGES = 16


def sanitize_label(label: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip())
    text = text.strip("-._")
    return text or "capture"


def safe_git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if completed.returncode == 0:
            value = completed.stdout.strip()
            return value or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def ndef_id_from_block(block: bytes) -> str | None:
    if len(block) < 16:
        return None
    return block[12:16][::-1].hex().upper()


def block_pages_dict(block: bytes) -> dict[str, str]:
    return {
        f"0x{EEPROM_WATCH_START_PAGE + index:02X}": block[
            index * 4 : (index + 1) * 4
        ].hex(" ").upper()
        for index in range(8)
    }


@dataclass
class CaptureConfig:
    port: str
    label: str
    state: str = "unspecified"
    notes: str = ""
    samples: int = 3
    interval_ms: float = 250.0
    output_dir: Path = field(
        default_factory=lambda: Path("captures") / "application-block"
    )
    include_full_dump: bool = False
    verbose: bool = False
    timeout: float = 2.0
    wait_tag_s: float = 15.0


@dataclass
class CaptureResult:
    directory: Path
    metadata: dict[str, Any]


class ApplicationBlockCapture:
    """Repeated read-only capture of EEPROM pages 0x30–0x37."""

    def __init__(
        self,
        config: CaptureConfig,
        *,
        client_factory: Callable[[str, float], Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        wall_clock: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or (
            lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)
        )
        self._sleep = sleep or time.sleep
        self._wall_clock = wall_clock or (
            lambda: datetime.now().astimezone().isoformat()
        )

    def run(self) -> CaptureResult:
        config = self.config
        if config.samples < 1:
            raise ValueError("--samples musí být >= 1")

        pending = create_capture_dir(
            Path(config.output_dir),
            "pending",
            when=datetime.now(),
        )
        # Rename later to include UID + label.
        started = self._wall_clock()
        samples_out: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        blocks: list[bytes] = []
        uid: str | None = None
        get_version_hex: str | None = None
        full_dump: bytes | None = None

        client = self._client_factory(config.port, config.timeout)
        entered = False
        try:
            enter = getattr(client, "__enter__", None)
            if callable(enter):
                client = enter()
                entered = True

            tag = self._wait_for_tag(client)
            uid = tag.id_hex
            ntag = NtagI2CPlus(client)
            version = ntag.get_version()
            get_version_hex = version.raw.hex(" ").upper()

            for index in range(1, config.samples + 1):
                try:
                    block = ntag.read_eeprom_range(
                        EEPROM_WATCH_START_PAGE,
                        EEPROM_WATCH_END_PAGE,
                    )
                    if len(block) != EEPROM_WATCH_SIZE_BYTES:
                        raise SerialCommunicationError(
                            f"Neočekávaná délka bloku: {len(block)} B"
                        )
                    blocks.append(block)
                    sample = {
                        "sample_index": index,
                        "ok": True,
                        "timestamp": self._wall_clock(),
                        "raw_hex": block.hex(" ").upper(),
                        "pages": block_pages_dict(block),
                        "identifier_le": block[12:16].hex(" ").upper(),
                        "ndef_id_derived": ndef_id_from_block(block),
                    }
                    samples_out.append(sample)
                    if config.verbose:
                        print(f"[sample {index}/{config.samples}] {sample['raw_hex']}")
                except (ElatecError, SerialCommunicationError, ValueError) as exc:
                    errors.append(
                        {
                            "sample_index": index,
                            "timestamp": self._wall_clock(),
                            "error": str(exc),
                        }
                    )
                    samples_out.append(
                        {
                            "sample_index": index,
                            "ok": False,
                            "timestamp": self._wall_clock(),
                            "error": str(exc),
                        }
                    )
                    if config.verbose:
                        print(f"[sample {index}] ERROR: {exc}")
                if index < config.samples:
                    self._sleep(config.interval_ms / 1000.0)

            if config.include_full_dump:
                try:
                    full_dump = self._read_full_dump(ntag)
                except (ElatecError, SerialCommunicationError, ValueError) as exc:
                    errors.append(
                        {
                            "phase": "full_dump",
                            "timestamp": self._wall_clock(),
                            "error": str(exc),
                        }
                    )
        finally:
            try:
                client.set_rf_off()
            except Exception:
                pass
            if entered:
                exit_ = getattr(client, "__exit__", None)
                if callable(exit_):
                    try:
                        exit_(None, None, None)
                    except Exception:
                        pass

        unique = {block.hex() for block in blocks}
        stable = len(blocks) > 0 and len(unique) == 1 and not errors
        representative = blocks[0] if blocks else None
        ndef_id = ndef_id_from_block(representative) if representative else None

        metadata: dict[str, Any] = {
            "schema_version": 1,
            "tool": "capture-application-block",
            "tool_version": __version__,
            "git_commit": safe_git_commit(),
            "read_only": True,
            "source_type": "physical_tag",
            "uid": uid,
            "get_version": get_version_hex,
            "ndef_id": ndef_id,
            "label": config.label,
            "state": config.state,
            "notes": config.notes,
            "started_at": started,
            "finished_at": self._wall_clock(),
            "port": config.port,
            "sample_count": config.samples,
            "successful_samples": len(blocks),
            "failed_samples": len(errors),
            "unique_block_values": len(unique),
            "stable_across_samples": stable,
            "block_start_page": EEPROM_WATCH_START_PAGE,
            "block_end_page": EEPROM_WATCH_END_PAGE,
            "include_full_dump": bool(config.include_full_dump and full_dump),
            "interval_ms": config.interval_ms,
        }

        directory = self._finalize_directory(pending, uid, config.label)
        self._write_outputs(
            directory,
            metadata,
            samples_out,
            representative,
            full_dump,
            errors,
        )
        return CaptureResult(directory=directory, metadata=metadata)

    def _wait_for_tag(self, client: Any):
        deadline = time.monotonic() + self.config.wait_tag_s
        while True:
            tag = client.search_tag()
            if tag is not None:
                return tag
            if time.monotonic() >= deadline:
                raise SerialCommunicationError("NFC tag nebyl nalezen.")
            self._sleep(0.12)

    def _read_full_dump(self, ntag: NtagI2CPlus) -> bytes:
        chunks: list[bytes] = []
        page = FULL_DUMP_START_PAGE
        while page <= FULL_DUMP_END_PAGE:
            end = min(page + FULL_DUMP_CHUNK_PAGES - 1, FULL_DUMP_END_PAGE)
            chunks.append(ntag.read_eeprom_range(page, end))
            page = end + 1
        return b"".join(chunks)

    def _finalize_directory(
        self,
        pending: Path,
        uid: str | None,
        label: str,
    ) -> Path:
        stamp = pending.name.rsplit("_", 1)[0]
        uid_part = (uid or "UNKNOWN").upper()
        label_part = sanitize_label(label)
        target = pending.parent / f"{stamp}_{uid_part}_{label_part}"
        suffix = 1
        while target.exists():
            target = pending.parent / f"{stamp}_{uid_part}_{label_part}_{suffix}"
            suffix += 1
        try:
            pending.rename(target)
            return target
        except OSError:
            return pending

    def _write_outputs(
        self,
        directory: Path,
        metadata: dict[str, Any],
        samples: list[dict[str, Any]],
        representative: bytes | None,
        full_dump: bytes | None,
        errors: list[dict[str, Any]],
    ) -> None:
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with (directory / "samples.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for sample in samples:
                handle.write(
                    json.dumps(sample, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )

        if representative is not None:
            (directory / "application_block.bin").write_bytes(representative)
            report = analyze_application_block(
                representative,
                source=str(directory),
                uid=metadata.get("uid"),
                ndef_id_hex=metadata.get("ndef_id") or "AA2CD0C9",
            )
            payload = report.to_dict()
            payload["label"] = metadata.get("label")
            payload["state"] = metadata.get("state")
            payload["notes"] = metadata.get("notes")
            payload["stable_across_samples"] = metadata.get("stable_across_samples")
            (directory / "application_block.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (directory / "application_block.txt").write_text(
                report.to_text(),
                encoding="utf-8",
            )

        if full_dump is not None:
            (directory / "full_dump.bin").write_bytes(full_dump)
            pages = {
                f"0x{index:02X}": full_dump[index * 4 : (index + 1) * 4].hex(" ").upper()
                for index in range(len(full_dump) // 4)
            }
            (directory / "full_dump.json").write_text(
                json.dumps(
                    {
                        "uid": metadata.get("uid"),
                        "start_page": FULL_DUMP_START_PAGE,
                        "end_page": FULL_DUMP_END_PAGE,
                        "byte_count": len(full_dump),
                        "pages": pages,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        if errors:
            with (directory / "errors.jsonl").open(
                "w", encoding="utf-8", newline="\n"
            ) as handle:
                for item in errors:
                    handle.write(
                        json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )

        (directory / "report.txt").write_text(
            self._build_report(metadata, samples, representative),
            encoding="utf-8",
        )

    def _build_report(
        self,
        metadata: dict[str, Any],
        samples: list[dict[str, Any]],
        representative: bytes | None,
    ) -> str:
        lines = [
            "Application Block Capture",
            "=========================",
            "",
            "Mode: READ-ONLY",
            f"UID: {metadata.get('uid')}",
            f"GET_VERSION: {metadata.get('get_version')}",
            f"NDEF ID (derived LE from 0x33): {metadata.get('ndef_id')}",
            f"Label: {metadata.get('label')}",
            f"State: {metadata.get('state')}",
            f"Notes: {metadata.get('notes')}",
            f"Samples: {metadata.get('successful_samples')}/"
            f"{metadata.get('sample_count')} ok",
            f"Stable across samples: {metadata.get('stable_across_samples')}",
            f"Unique block values: {metadata.get('unique_block_values')}",
            "",
        ]
        if representative is not None:
            lines.append(f"Representative: {representative.hex(' ').upper()}")
            lines.append(f"ASCII: {safe_ascii_preview(representative)}")
            lines.append("")
            for page, hex_value in block_pages_dict(representative).items():
                lines.append(f"  {page}: {hex_value}")
        lines.append("")
        lines.append("Sample outcomes:")
        for sample in samples:
            if sample.get("ok"):
                lines.append(
                    f"  #{sample['sample_index']}: OK {sample.get('raw_hex')}"
                )
            else:
                lines.append(
                    f"  #{sample['sample_index']}: FAIL {sample.get('error')}"
                )
        lines.append("")
        return "\n".join(lines) + "\n"


def load_capture_directory(path: Path) -> dict[str, Any]:
    """Load a capture directory produced by ApplicationBlockCapture."""
    path = Path(path)
    meta_path = path / "metadata.json"
    if not meta_path.exists():
        raise ValueError(f"Nevalidní capture (chybí metadata.json): {path}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    block_bin = path / "application_block.bin"
    block_json = path / "application_block.json"
    block: bytes | None = None
    if block_bin.exists():
        block = block_bin.read_bytes()
    elif block_json.exists():
        document = json.loads(block_json.read_text(encoding="utf-8"))
        if "raw_hex" in document:
            from .dump_loaders import parse_hex_bytes

            block = parse_hex_bytes(document["raw_hex"])
        elif "pages" in document:
            from .dump_loaders import extract_pages_from_json

            block = pages_to_block(extract_pages_from_json(document))
    samples: list[dict[str, Any]] = []
    samples_path = path / "samples.jsonl"
    if samples_path.exists():
        for line in samples_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                samples.append(json.loads(line))
    valid = (
        isinstance(metadata, dict)
        and block is not None
        and len(block) == EEPROM_WATCH_SIZE_BYTES
    )
    return {
        "path": path,
        "metadata": metadata,
        "block": block,
        "samples": samples,
        "valid": valid,
        "warning": None if valid else "incomplete or invalid capture",
    }
