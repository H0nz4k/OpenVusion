from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class CapturePhase(str, Enum):
    IDENTIFICATION = "IDENTIFICATION"
    EEPROM = "EEPROM"
    APPLICATION_BLOCK = "APPLICATION"
    SESSION = "SESSION"
    VERIFYING = "VERIFYING"
    SAVING = "SAVING"


class FinishStatus(str, Enum):
    COMPLETED_SUCCESSFULLY = "completed_successfully"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    PARTIAL = "partial"
    ABORTED = "aborted"
    DUPLICATE_SKIPPED = "duplicate_skipped"


@dataclass(frozen=True)
class ReaderCandidate:
    device: str
    description: str
    hwid: str
    vid: int | None = None
    pid: int | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None
    score: int = 0
    verified: bool = False
    verify_error: str | None = None

    @property
    def label(self) -> str:
        bits = [self.device]
        if self.product:
            bits.append(self.product)
        elif self.description:
            bits.append(self.description)
        if self.serial_number:
            bits.append(f"S/N {self.serial_number}")
        return " | ".join(bits)


@dataclass
class CaptureProgress:
    phase: CapturePhase
    sample_index: int = 0
    sample_total: int = 0
    message: str = ""


@dataclass
class FieldCaptureResult:
    uid: str | None
    get_version: str | None
    directory: str | None
    finish_status: FinishStatus
    application_block_hex: str | None = None
    sha256: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duplicate: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    # ok | error | skipped | pending — filled by one-shot / continuous capture.
    phase_status: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["finish_status"] = self.finish_status.value
        return data


@dataclass
class CollectorConfig:
    capture_root: str
    data_root: str | None = None
    application_samples: int = 5
    full_dump_samples: int = 0
    session_duration_seconds: float = 2.0
    session_interval_ms: float = 50.0
    allow_duplicate: bool = False
    wait_for_removal: bool = True
    handshake_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 0.25
    include_session: bool = True
    include_full_dump: bool = False
    # After each one-tag sniff, pack all artifacts as DDMMYYYY_HH_MM.tar here.
    export_bundle_root: str | None = "/home/sniffer/capture"
    # One-shot retry / timeout controls (used by capture_one / run_once).
    phase_retry_count: int = 3
    phase_retry_delay_ms: float = 100.0
    tag_acquire_timeout_seconds: float = 30.0
    capture_timeout_seconds: float = 120.0
    label: str = "field"
    state: str = "field"
    notes: str = ""

    def resolved_data_root(self) -> str:
        if self.data_root:
            return self.data_root
        return str(Path(self.capture_root).parent)
