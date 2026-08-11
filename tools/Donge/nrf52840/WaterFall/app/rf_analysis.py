from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, asdict
from typing import Iterable


BLE_ADV_CHANNELS = {
    37: 2402,
    38: 2426,
    39: 2480,
}

IEEE802154_CHANNELS = {
    ch: 2405 + 5 * (ch - 11)
    for ch in range(11, 27)
}

WIFI_24_CHANNELS = {
    **{ch: 2412 + 5 * (ch - 1) for ch in range(1, 14)},
    14: 2484,
}


@dataclass
class SpectralCandidate:
    start_mhz: int
    end_mhz: int
    center_mhz: float
    width_mhz: int
    peak_mhz: int
    peak_rssi_dbm: int
    median_dbm: float
    delta_median_db: float
    shape: str
    overlaps: list[dict]
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def summarize_points(points: list[dict]) -> dict:
    values = [int(p["rssi_dbm"]) for p in points]
    if not values:
        return {}

    peak = max(points, key=lambda p: int(p["rssi_dbm"]))
    med = statistics.median(values)
    mean = statistics.fmean(values)
    ordered = sorted(values)
    p90_idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.9) - 1))

    return {
        "peak_freq_mhz": int(peak["freq_mhz"]),
        "peak_rssi_dbm": int(peak["rssi_dbm"]),
        "median_dbm": round(float(med), 2),
        "mean_dbm": round(float(mean), 2),
        "p90_dbm": int(ordered[p90_idx]),
        "min_dbm": int(min(values)),
        "max_dbm": int(max(values)),
        "dynamic_range_db": round(float(max(values) - min(values)), 2),
        "bins": len(values),
        "above_median_10db": sum(1 for v in values if v >= med + 10),
        "above_median_20db": sum(1 for v in values if v >= med + 20),
    }


def _nearest(mapping: dict[int, int], freq_mhz: float) -> tuple[int, int, float]:
    ch, center = min(mapping.items(), key=lambda item: abs(item[1] - freq_mhz))
    return ch, center, abs(center - freq_mhz)


def channel_annotations(start_mhz: int, end_mhz: int, peak_mhz: int) -> list[dict]:
    """
    Return protocol/channel *overlaps*, not protocol identifications.

    An RSSI energy survey has no packet framing or modulation decoder, so the
    result must never claim that a protocol/device was positively identified.
    """
    out: list[dict] = []

    # BLE advertising channels are single center frequencies. 1 MHz tolerance
    # makes sense for our 1 MHz survey bins.
    for ch, center in BLE_ADV_CHANNELS.items():
        if start_mhz - 1 <= center <= end_mhz + 1:
            out.append({
                "protocol": "Bluetooth LE advertising",
                "channel": ch,
                "center_mhz": center,
                "relation": "frequency overlap",
            })

    # IEEE 802.15.4 channels are 5 MHz apart; the occupied signal is narrower
    # than Wi-Fi, so keep a small overlap tolerance.
    for ch, center in IEEE802154_CHANNELS.items():
        if start_mhz - 2 <= center <= end_mhz + 2:
            out.append({
                "protocol": "IEEE 802.15.4",
                "channel": ch,
                "center_mhz": center,
                "relation": "frequency overlap",
            })

    # For Wi-Fi report only nearby centers. Spectral width/shape is handled by
    # the caller; this is not a decoder.
    wifi_ch, wifi_center, wifi_delta = _nearest(WIFI_24_CHANNELS, peak_mhz)
    if wifi_delta <= 12:
        out.append({
            "protocol": "Wi-Fi 2.4 GHz",
            "channel": wifi_ch,
            "center_mhz": wifi_center,
            "relation": "nearest channel center",
            "center_delta_mhz": round(wifi_delta, 2),
        })

    return out


def _segments(active: list[dict], max_gap_mhz: int) -> list[list[dict]]:
    if not active:
        return []
    active = sorted(active, key=lambda p: int(p["freq_mhz"]))
    result: list[list[dict]] = [[active[0]]]
    for p in active[1:]:
        if int(p["freq_mhz"]) - int(result[-1][-1]["freq_mhz"]) <= max_gap_mhz:
            result[-1].append(p)
        else:
            result.append([p])
    return result


def detect_candidates(
    points: list[dict],
    threshold_above_median_db: float = 12.0,
    absolute_floor_dbm: int = -92,
    max_gap_mhz: int = 2,
    min_bins: int = 1,
) -> list[dict]:
    if not points:
        return []

    values = [int(p["rssi_dbm"]) for p in points]
    med = float(statistics.median(values))
    threshold = max(float(absolute_floor_dbm), med + float(threshold_above_median_db))
    active = [p for p in points if int(p["rssi_dbm"]) >= threshold]
    candidates: list[dict] = []

    for seg in _segments(active, max_gap_mhz=max_gap_mhz):
        if len(seg) < min_bins:
            continue

        start = int(seg[0]["freq_mhz"])
        end = int(seg[-1]["freq_mhz"])
        peak = max(seg, key=lambda p: int(p["rssi_dbm"]))
        peak_freq = int(peak["freq_mhz"])
        peak_rssi = int(peak["rssi_dbm"])
        width = max(1, end - start + 1)

        if width >= 12:
            shape = "wideband"
            note = "Širokopásmová aktivita; může odpovídat Wi-Fi nebo jinému širokopásmovému zdroji."
        elif width <= 3:
            shape = "narrowband"
            note = "Úzkopásmová/burst aktivita; z RSSI samotného nelze určit protokol ani zařízení."
        else:
            shape = "midband"
            note = "Středně široká aktivita; nutná časová korelace nebo packet capture."

        candidate = SpectralCandidate(
            start_mhz=start,
            end_mhz=end,
            center_mhz=round((start + end) / 2.0, 2),
            width_mhz=width,
            peak_mhz=peak_freq,
            peak_rssi_dbm=peak_rssi,
            median_dbm=round(med, 2),
            delta_median_db=round(peak_rssi - med, 2),
            shape=shape,
            overlaps=channel_annotations(start, end, peak_freq),
            note=note,
        )
        candidates.append(candidate.to_dict())

    return sorted(candidates, key=lambda c: c["peak_rssi_dbm"], reverse=True)


def frequency_labels(freq_mhz: int) -> list[str]:
    labels: list[str] = []
    for ch, center in BLE_ADV_CHANNELS.items():
        if abs(center - freq_mhz) <= 1:
            labels.append(f"BLE adv ch {ch}")
    for ch, center in IEEE802154_CHANNELS.items():
        if abs(center - freq_mhz) <= 2:
            labels.append(f"802.15.4 ch {ch}")
    wifi_ch, center, delta = _nearest(WIFI_24_CHANNELS, freq_mhz)
    if delta <= 11:
        labels.append(f"Wi-Fi ch {wifi_ch} ({center} MHz center)")
    return labels
