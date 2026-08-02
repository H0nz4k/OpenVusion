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
    SUCCESS_SIGNAL = "STATE_SUCCESS_SIGNAL"
    PARTIAL = "STATE_PARTIAL"
    ERROR = "STATE_ERROR"
    CANCELLED = "STATE_CANCELLED"
    SHUTDOWN = "STATE_SHUTDOWN"


class DipMode(str, Enum):
    """Working names — easy to rename later without changing wire map."""

    NORMAL = "MODE_NORMAL"
    FAST = "MODE_FAST"
    DEEP = "MODE_DEEP"
    SERVICE = "MODE_SERVICE"


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
    dip_mode: DipMode = DipMode.NORMAL
    active_cycle_mode: DipMode | None = None
    wlan: WlanStatus = WlanStatus.OFFLINE
    wlan_ip: str | None = None
    last_error: str | None = None
    collector_running: bool = False
    collector_progress: str = ""
    last_outcome: CollectorOutcome | None = None
    extras: dict[str, Any] = field(default_factory=dict)
