import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.device_registry import DeviceRegistry


def test_ble_device_merge():
    r = DeviceRegistry()
    p = {
        "address": "AA:BB:CC:DD:EE:FF",
        "host_time": "2026-08-11T01:00:00.000",
        "name": "sensor",
        "local_name": "sensor-local",
        "rssi_dbm": -60,
        "manufacturer_data": [{"company_id": 0x0059, "company_id_hex": "0x0059", "data_hex": "0102"}],
        "service_uuids": ["0000180f-0000-1000-8000-00805f9b34fb"],
        "service_data": {},
    }
    d1 = r.observe_ble(p)
    p["rssi_dbm"] = -50
    p["host_time"] = "2026-08-11T01:00:01.000"
    d2 = r.observe_ble(p)
    assert d2["seen_count"] == 2
    assert d2["strongest_rssi_dbm"] == -50
    assert d2["manufacturer_data"][0]["company_name"] == "Nordic Semiconductor ASA"
    assert d2["service_uuids"][0]["name"] == "Battery Service"
