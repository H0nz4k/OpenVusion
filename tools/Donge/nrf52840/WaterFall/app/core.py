from __future__ import annotations

import asyncio
import csv
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import WebSocket


@dataclass
class State:
    version: str = ""
    probe_connected: bool = False
    probe_port: str = ""
    probe_product: str = ""
    probe_serial: str = ""
    probe_error: str = ""
    firmware: str = ""
    scan_enabled: bool = False
    watch_enabled: bool = False
    watch_freq_mhz: int = 0
    watch_period_ms: int = 0
    rssi_mode: str = "LAST"
    sweep_step_mhz: int = 1
    ble_enabled: bool = False
    ble_connected: bool = False
    ble_mode: str = ""
    ble_error: str = ""
    ble_device_count: int = 0
    packet_count: int = 0
    nfc_connected: bool = False
    nfc_error: str = ""
    nfc_present: bool = False
    nfc_uid: str = ""
    relay_available: bool = False
    relay_power_on: bool = False
    sweep_count: int = 0
    rf_event_count: int = 0
    recording: bool = False
    recording_file: str = ""
    experiment_recording: bool = False
    experiment_file: str = ""
    capture_active: bool = False
    capture_session_id: str = ""
    capture_zip: str = ""
    tshark_available: bool = False
    last_rx_iso: str = ""
    last_line: str = ""
    mock_mode: bool = False


class Hub:
    def __init__(self):
        self.clients = set()
        self.loop = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def send(self, payload):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self.loop)


class CsvWriter:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.fp = None
        self.writer = None
        self.path = None

    def start(self):
        with self.lock:
            if self.fp:
                return str(self.path)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = self.directory / f"waterfall_rf_{stamp}.csv"
            self.fp = self.path.open("w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.fp)
            self.writer.writerow([
                "host_time", "sweep", "device_ms", "freq_mhz", "rssi_dbm",
                "peak_freq_mhz", "peak_rssi_dbm", "median_dbm", "mean_dbm",
            ])
            self.fp.flush()
            return str(self.path)

    def stop(self):
        with self.lock:
            if self.fp:
                self.fp.flush()
                self.fp.close()
            self.fp = None
            self.writer = None

    def write(self, sweep: dict):
        with self.lock:
            if not self.writer:
                return
            summary = sweep.get("summary", {})
            for p in sweep.get("points", []):
                self.writer.writerow([
                    sweep.get("host_time", ""), sweep.get("sweep", ""),
                    sweep.get("device_ms", ""), p.get("freq_mhz", ""), p.get("rssi_dbm", ""),
                    summary.get("peak_freq_mhz", ""), summary.get("peak_rssi_dbm", ""),
                    summary.get("median_dbm", ""), summary.get("mean_dbm", ""),
                ])
            self.fp.flush()
