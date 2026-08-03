"""HWSniff v2 device / DIP / collector state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceState(str, Enum):
    BOOT = "STATE_BOOT"
    READY = "STATE_READY"
    POSITIONING = "STATE_POSITIONING"
    READ = "STATE_READ"
    READ_COMPLETE = "STATE_READ_COMPLETE"
    SAVE = "STATE_SAVE"
    ERROR1 = "STATE_ERROR1"
    ERROR2 = "STATE_ERROR2"
    ERROR3 = "STATE_ERROR3"
    CANCELLED = "STATE_CANCELLED"
    SWEETP = "STATE_SWEETP"
    SHUTDOWN = "STATE_SHUTDOWN"


class DipMode(str, Enum):
    MAIN = "MODE_MAIN"
    SWEETP = "MODE_SWEETP"
    ERROR3 = "MODE_ERROR3"
    SWEET_POINT = "MODE_SWEETP"  # legacy alias


class SweetBand(str, Enum):
    NONE = "none"
    BAD = "bad"
    BORDERLINE = "borderline"
    USABLE = "usable"
    GOOD = "good"


class SweetQuality(str, Enum):
    """Legacy quality enum mapped onto v2 bands."""

    NONE = "none"
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


# READ progress phases → 6-step LED bar
READ_PHASE_STEPS: dict[str, int] = {
    "uid_confirm": 1,
    "identification": 2,
    "eeprom": 3,
    "application": 4,
    "session": 5,
    "verification": 6,
}


@dataclass
class RuntimeState:
    device_state: DeviceState = DeviceState.BOOT
    dip_mode: DipMode = DipMode.MAIN
    dip1_on: bool = False
    dip2_on: bool = False
    active_cycle_mode: DipMode | None = None
    wlan: WlanStatus = WlanStatus.OFFLINE
    wlan_ip: str | None = None
    last_error: str | None = None
    collector_running: bool = False
    collector_progress: str = ""
    last_outcome: CollectorOutcome | None = None
    sweet_band: SweetBand = SweetBand.NONE
    sweet_score: float | None = None
    sweet_has_tag: bool = False
    locked_uid: str | None = None
    read_step: int = 0  # 0..6
    positioning_score: float | None = None
    reader_port: str | None = None
    reader_version: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def sweet_quality(self) -> SweetQuality:
        mapping = {
            SweetBand.NONE: SweetQuality.NONE,
            SweetBand.BAD: SweetQuality.LOW,
            SweetBand.BORDERLINE: SweetQuality.LOW,
            SweetBand.USABLE: SweetQuality.MEDIUM,
            SweetBand.GOOD: SweetQuality.HIGH,
        }
        return mapping[self.sweet_band]

    @sweet_quality.setter
    def sweet_quality(self, value: SweetQuality) -> None:
        mapping = {
            SweetQuality.NONE: SweetBand.NONE,
            SweetQuality.LOW: SweetBand.BAD,
            SweetQuality.MEDIUM: SweetBand.USABLE,
            SweetQuality.HIGH: SweetBand.GOOD,
        }
        self.sweet_band = mapping.get(value, SweetBand.NONE)

    @property
    def dip2_reserved_on(self) -> bool:
        return self.dip2_on

    @dip2_reserved_on.setter
    def dip2_reserved_on(self, value: bool) -> None:
        self.dip2_on = value
