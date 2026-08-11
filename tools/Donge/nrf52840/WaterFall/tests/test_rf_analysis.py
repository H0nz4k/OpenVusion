import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rf_analysis import detect_candidates, frequency_labels


def test_narrow_peak():
    pts = [{"freq_mhz": f, "rssi_dbm": -101} for f in range(2400, 2501)]
    for p in pts:
        if p["freq_mhz"] == 2453:
            p["rssi_dbm"] = -50
    c = detect_candidates(pts)
    assert c
    assert c[0]["peak_mhz"] == 2453
    assert c[0]["shape"] == "narrowband"


def test_wifi_broad_shape():
    pts = [{"freq_mhz": f, "rssi_dbm": -102} for f in range(2400, 2501)]
    for p in pts:
        if 2428 <= p["freq_mhz"] <= 2446:
            p["rssi_dbm"] = -65
    c = detect_candidates(pts, threshold_above_median_db=10)
    assert c[0]["shape"] == "wideband"
    assert any(x["protocol"].startswith("Wi-Fi") for x in c[0]["overlaps"])


def test_channel_labels():
    assert any("BLE adv ch 37" in x for x in frequency_labels(2402))
    assert any("802.15.4 ch 11" in x for x in frequency_labels(2405))
