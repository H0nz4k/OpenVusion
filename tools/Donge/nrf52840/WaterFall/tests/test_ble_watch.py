from types import SimpleNamespace

from app.ble_watch import BleWatcher


def test_packet_conversion():
    dev = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Demo", rssi=-70)
    ad = SimpleNamespace(
        manufacturer_data={0x0059: b"\x01\x02"},
        service_data={"180f": b"\x64"},
        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],
        rssi=-55,
        local_name="Demo Local",
        tx_power=-4,
    )
    p = BleWatcher._packet(dev, ad)
    assert p["protocol"] == "BLE-ADV"
    assert p["address"] == "AA:BB:CC:DD:EE:FF"
    assert p["rssi_dbm"] == -55
    assert p["manufacturer_data"][0]["company_id"] == 0x0059
    assert "MFG[0x0059]=0102" in p["raw_summary"]
