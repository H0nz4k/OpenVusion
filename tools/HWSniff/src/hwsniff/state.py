"""Headless Pi Zero 2 W device / DIP / collector state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceState(str, Enum):
    BOOT = "STATE_BOOT"
    READY = "STATE_READY"
    WAITING = "STATE_WAITING"
    READING = "STATE_READING"
    SAVING = "STATE_SAVING"
    SUCCESS_WAIT_ACK = "STATE_SUCCESS_WAIT_ACK"
    PARTIAL = "STATE_PARTIAL"
    ERROR = "STATE_ERROR"
    CANCELLED = "STATE_CANCELLED"
    SWEET_POINT = "STATE_SWEET_POINT"
    SHUTDOWN = "STATE_SHUTDOWN"


class DipMode(str, Enum):
    """DIP1 selects operating mode; DIP2 is reserved."""

    MAIN = "MODE_MAIN"
    SWEET_POINT = "MODE_SWEET_POINT"


class SweetQuality(str, Enum):
    NONE = "none"  # no tag
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WlanStatus(str, Enum):
    OFFLINE = "WLAN_OFFLINE"
    CONNECTING = "WLAN_CONNECTING"
    CONNECTED = "WLAN_CONNECTED"


class CollectorOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class RuntimeState:
    device_state: DeviceState = DeviceState.BOOT
    dip_mode: DipMode = DipMode.MAIN
    dip2_reserved_on: bool = False
    active_cycle_mode: DipMode | None = None
    wlan: WlanStatus = WlanStatus.OFFLINE
    wlan_ip: str | None = None
    last_error: str | None = None
    collector_running: bool = False
    collector_progress: str = ""
    last_outcome: CollectorOutcome | None = None
    sweet_quality: SweetQuality = SweetQuality.NONE
    sweet_score: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)
