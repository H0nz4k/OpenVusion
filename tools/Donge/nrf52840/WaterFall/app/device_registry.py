from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime


# Common Bluetooth SIG Company Identifiers used only as a convenience cache.
# Unknown IDs are kept numeric; no guessed manufacturer name is invented.
COMPANY_IDS = {
    0x0006: "Microsoft",
    0x000D: "Texas Instruments Inc.",
    0x0025: "NXP B.V.",
    0x004C: "Apple, Inc.",
    0x0059: "Nordic Semiconductor ASA",
    0x005D: "Realtek Semiconductor Corporation",
    0x0065: "HP, Inc.",
    0x006B: "Polar Electro OY",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google",
}

SERVICE_UUID_NAMES = {
    "1800": "Generic Access",
    "1801": "Generic Attribute",
    "180a": "Device Information",
    "180d": "Heart Rate",
    "180f": "Battery Service",
    "181a": "Environmental Sensing",
    "181c": "User Data",
    "181d": "Weight Scale",
    "181f": "Continuous Glucose Monitoring",
    "1826": "Fitness Machine",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def short_uuid(value: str) -> str | None:
    v = value.lower()
    prefix = "0000"
    suffix = "-0000-1000-8000-00805f9b34fb"
    if v.startswith(prefix) and v.endswith(suffix) and len(v) == 36:
        return v[4:8]
    if len(v) == 4:
        return v
    return None


def uuid_label(value: str) -> str:
    short = short_uuid(value)
    if short and short in SERVICE_UUID_NAMES:
        return SERVICE_UUID_NAMES[short]
    return value


class DeviceRegistry:
    """Thread-safe inventory built from passive/host-side observations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}

    def observe_ble(self, packet: dict) -> dict:
        address = str(packet.get("address") or "UNKNOWN").upper()
        ts = str(packet.get("host_time") or now_iso())
        with self._lock:
            d = self._devices.get(address)
            if d is None:
                d = {
                    "id": address,
                    "protocol": "Bluetooth LE",
                    "address": address,
                    "first_seen": ts,
                    "last_seen": ts,
                    "seen_count": 0,
                    "name": "",
                    "local_name": "",
                    "latest_rssi_dbm": None,
                    "strongest_rssi_dbm": None,
                    "tx_power_dbm": None,
                    "manufacturer_data": [],
                    "service_uuids": [],
                    "service_data": {},
                    "capture_level": "BlueZ advertising report",
                    "identification_note": (
                        "Identita je odvozena pouze z BLE advertising dat. "
                        "Název/výrobce nemusí být přítomen a randomizovaná BLE adresa nemusí být stabilní."
                    ),
                }
                self._devices[address] = d

            d["last_seen"] = ts
            d["seen_count"] += 1
            if packet.get("name"):
                d["name"] = packet["name"]
            if packet.get("local_name"):
                d["local_name"] = packet["local_name"]

            rssi = packet.get("rssi_dbm")
            if rssi is not None:
                rssi = int(rssi)
                d["latest_rssi_dbm"] = rssi
                if d["strongest_rssi_dbm"] is None or rssi > d["strongest_rssi_dbm"]:
                    d["strongest_rssi_dbm"] = rssi

            if packet.get("tx_power_dbm") is not None:
                d["tx_power_dbm"] = packet["tx_power_dbm"]

            manufacturer_rows = []
            for item in packet.get("manufacturer_data", []):
                cid = int(item.get("company_id", -1))
                manufacturer_rows.append({
                    **item,
                    "company_name": COMPANY_IDS.get(cid, ""),
                })
            if manufacturer_rows:
                d["manufacturer_data"] = manufacturer_rows

            services = []
            for uuid in packet.get("service_uuids", []):
                services.append({"uuid": uuid, "name": uuid_label(uuid)})
            if services:
                d["service_uuids"] = services

            if packet.get("service_data"):
                d["service_data"] = packet["service_data"]

            return deepcopy(d)

    def list(self) -> list[dict]:
        with self._lock:
            values = [deepcopy(v) for v in self._devices.values()]
        return sorted(values, key=lambda d: d.get("last_seen", ""), reverse=True)

    def get(self, device_id: str) -> dict | None:
        key = device_id.upper()
        with self._lock:
            d = self._devices.get(key)
            return deepcopy(d) if d else None

    def clear(self) -> None:
        with self._lock:
            self._devices.clear()
