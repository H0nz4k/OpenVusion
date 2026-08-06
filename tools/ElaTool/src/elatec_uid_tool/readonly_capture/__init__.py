"""Shared read-only single-tag capture engine (PCSniff + HWSniff).

The public ``CaptureProbe`` export is technology-aware: it preserves the
verified NTAG I2C Plus path and auto-dispatches protocol-confirmed FeliCa /
NFC Forum Type 3 targets to the read-only FeliCa branch.
"""

from .capture import CaptureProbe as BaseCaptureProbe, ProbeConfig, ProbeResult
from .auto_probe import AutoCaptureProbe

# Shared consumers (PCSniff / FieldCollector / HWSniff) keep importing the same
# name, but now receive the technology-aware implementation.
CaptureProbe = AutoCaptureProbe

from .bridge import probe_to_field_result
from .persist import CaptureStore, make_capture_dir
from .status import OverallStatus, PhaseStatus, compute_overall

__all__ = [
    "AutoCaptureProbe",
    "BaseCaptureProbe",
    "CaptureProbe",
    "CaptureStore",
    "OverallStatus",
    "PhaseStatus",
    "ProbeConfig",
    "ProbeResult",
    "compute_overall",
    "make_capture_dir",
    "probe_to_field_result",
]
