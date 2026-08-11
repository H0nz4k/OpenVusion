from __future__ import annotations

import asyncio
import json
import math
import os
import random
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import serial
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .ble_watch import BleWatcher
from .core import CsvWriter, Hub, State
from .capture_session import CaptureSession
from .device_registry import DeviceRegistry
from .events import EventRecorder
from .nfc_watch import NfcWatcher
from .pcap_tools import TsharkInspector
from .probe_discovery import discover_probe
from .relay import RelayController
from .rf_analysis import detect_candidates, summarize_points
from .routes import register_routes


APP_VERSION = "0.4.0"
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
CONFIG_PATH = Path(
    os.environ.get(
        "WATERFALL_CONFIG",
        os.environ.get("OPENVUSION_RF_CONFIG", BASE_DIR / "config.json"),
    )
)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        example = BASE_DIR / "config.example.json"
        if example.exists():
            return json.loads(example.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Config nenalezen: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


CONFIG = load_config()
HISTORY_LIMIT = max(30, int(CONFIG.get("history_sweeps", 240)))
PACKET_LIMIT = max(100, int(CONFIG.get("packet_history", 1000)))
WATCH_LIMIT = max(100, int(CONFIG.get("watch_history", 1200)))
RF_EVENT_LIMIT = max(100, int(CONFIG.get("rf_event_history", 500)))

analyzer_settings = {
    "threshold_above_median_db": float(CONFIG.get("analyzer", {}).get("threshold_above_median_db", 12.0)),
    "absolute_floor_dbm": int(CONFIG.get("analyzer", {}).get("absolute_floor_dbm", -92)),
    "max_gap_mhz": int(CONFIG.get("analyzer", {}).get("max_gap_mhz", 2)),
    "min_bins": int(CONFIG.get("analyzer", {}).get("min_bins", 1)),
}
analyzer_lock = threading.Lock()



hub = Hub()
state = State(version=APP_VERSION, mock_mode=bool(CONFIG.get("mock_mode", False)))
csv_writer = CsvWriter(CONFIG["csv_dir"])
events = EventRecorder(CONFIG["experiment_dir"])
history = deque(maxlen=HISTORY_LIMIT)
watch_history = deque(maxlen=WATCH_LIMIT)
packet_history = deque(maxlen=PACKET_LIMIT)
rf_event_history = deque(maxlen=RF_EVENT_LIMIT)
history_lock = threading.Lock()
packet_lock = threading.Lock()
watch_lock = threading.Lock()
rf_event_lock = threading.Lock()
registry = DeviceRegistry()

capture = CaptureSession(
    CONFIG.get("capture_dir", "/var/lib/waterfall/sessions"),
    APP_VERSION,
    CONFIG,
)
capture.set_device_snapshot_provider(registry.list)

pcap = TsharkInspector(CONFIG.get("pcap_dir", "/var/lib/waterfall/pcap"))
state.tshark_available = pcap.available

relay_cfg = CONFIG.get("relay", {})
relay = (
    RelayController(
        relay_cfg.get("gpio_bcm", 17),
        relay_cfg.get("active_low", True),
        relay_cfg.get("default_power_on", True),
    )
    if relay_cfg.get("enabled", False)
    else None
)
if relay:
    state.relay_available = relay.status.available
    state.relay_power_on = relay.status.power_on


def broadcast_state():
    hub.send({"type": "state", "state": asdict(state)})


def emit_marker(kind: str, label: str, source: str = "SERVER", **data):
    marker = events.emit(kind, label, source, **data)
    payload = asdict(marker)
    capture.write("markers", payload)
    hub.send({"type": "marker", "marker": payload})
    return marker


def update_nfc_state(connected, error, present, uid):
    state.nfc_connected = bool(connected)
    state.nfc_error = error or ""
    state.nfc_present = bool(present)
    state.nfc_uid = uid or ""
    broadcast_state()


def update_ble_state(connected: bool, error: str, mode: str):
    state.ble_connected = bool(connected)
    state.ble_error = error or ""
    state.ble_mode = mode or ""
    broadcast_state()


def register_ble_packet(packet: dict):
    device = registry.observe_ble(packet)
    with packet_lock:
        packet_history.append(packet)
    state.packet_count += 1
    state.ble_device_count = len(registry.list())
    capture.write("packets", packet)
    hub.send({"type": "packet", "packet": packet})
    hub.send({"type": "device", "device": device})
    if state.packet_count % 10 == 0:
        broadcast_state()


def register_watch(sample: dict):
    with watch_lock:
        watch_history.append(sample)
    state.last_rx_iso = sample.get("host_time", "")
    state.watch_enabled = True
    state.watch_freq_mhz = int(sample.get("freq_mhz", 0))
    capture.write("watch", sample)
    hub.send(sample)


def register_sweep(sweep: dict):
    sweep["summary"] = summarize_points(sweep["points"])
    with analyzer_lock:
        settings = dict(analyzer_settings)
    candidates = detect_candidates(sweep["points"], **settings)
    sweep["candidates"] = candidates

    with history_lock:
        history.append(sweep)
    state.sweep_count = int(sweep["sweep"])
    state.last_rx_iso = sweep["host_time"]
    csv_writer.write(sweep)
    capture.write("sweeps", sweep)
    hub.send(sweep)

    if candidates:
        event = {
            "type": "rf_candidates",
            "host_time": sweep["host_time"],
            "sweep": sweep["sweep"],
            "candidates": candidates,
            "warning": "Spektrální kandidáti nejsou packet-level identifikace protokolu ani zařízení.",
        }
        with rf_event_lock:
            rf_event_history.append(event)
        state.rf_event_count += len(candidates)
        capture.write("rf_events", event)
        hub.send(event)




class ProbeWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q = deque()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    def command(self, value: str):
        with self.lock:
            self.q.append(value)

    def commands(self):
        out = []
        with self.lock:
            while self.q:
                out.append(self.q.popleft())
        return out

    @staticmethod
    def parse_sweep(line: str):
        if not line.startswith("SWEEP,"):
            return None
        try:
            parts = line.split(",")
            points, errors = [], []
            for item in parts[3:]:
                if ":" not in item:
                    continue
                f, r = item.split(":", 1)
                freq = int(f)
                if r.startswith("ERR"):
                    errors.append({"freq_mhz": freq, "error": r})
                else:
                    points.append({"freq_mhz": freq, "rssi_dbm": int(r)})
            if not points:
                return None
            return {
                "type": "sweep",
                "host_time": datetime.now().isoformat(timespec="milliseconds"),
                "sweep": int(parts[1]),
                "device_ms": int(parts[2]),
                "points": points,
                "rf_errors": errors,
            }
        except Exception:
            return None

    @staticmethod
    def parse_watch(line: str):
        if not line.startswith("RSSI,"):
            return None
        try:
            # RSSI,<seq>,<device_ms>,<freq_mhz>,<rssi>,<mode>
            p = line.split(",")
            return {
                "type": "watch",
                "host_time": datetime.now().isoformat(timespec="milliseconds"),
                "seq": int(p[1]),
                "device_ms": int(p[2]),
                "freq_mhz": int(p[3]),
                "rssi_dbm": int(p[4]),
                "rssi_mode": p[5] if len(p) > 5 else "",
            }
        except Exception:
            return None

    def _send(self, ser, cmd):
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()

    def run(self):
        cfg = CONFIG.get("rf_probe", {})
        if not cfg.get("enabled", True):
            return
        while not self.stop_event.is_set():
            try:
                found = discover_probe(cfg)
                port = found["device"]
                state.probe_port = port
                state.probe_product = found["product"]
                state.probe_serial = found["serial_number"]
                with serial.Serial(
                    port,
                    int(cfg.get("baudrate", 115200)),
                    timeout=0.25,
                    write_timeout=2.0,
                    rtscts=False,
                    dsrdtr=False,
                    xonxoff=False,
                ) as ser:
                    try:
                        ser.dtr = True
                    except Exception:
                        pass
                    try:
                        ser.rts = False
                    except Exception:
                        pass
                    time.sleep(max(0.1, int(cfg.get("connect_delay_ms", 350)) / 1000.0))
                    ser.reset_input_buffer()
                    state.probe_connected = True
                    state.probe_error = ""
                    broadcast_state()
                    emit_marker("RF_PROBE_ONLINE", f"{port} {found['product']}".strip(), "NRF52840", serial=found["serial_number"])
                    self._send(ser, "PING")
                    time.sleep(0.05)
                    self._send(ser, "INFO")
                    if cfg.get("auto_scan", True):
                        time.sleep(0.15)
                        self._send(ser, "SCAN START")

                    while not self.stop_event.is_set():
                        for cmd in self.commands():
                            self._send(ser, cmd)
                        raw = ser.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        state.last_line = line
                        sweep = self.parse_sweep(line)
                        if sweep:
                            register_sweep(sweep)
                            continue
                        sample = self.parse_watch(line)
                        if sample:
                            register_watch(sample)
                            continue

                        if line.startswith("FW="):
                            state.firmware = line[3:]
                        elif line.startswith("OK SCAN=ON"):
                            state.scan_enabled = True
                            state.watch_enabled = False
                        elif line.startswith("OK SCAN=OFF"):
                            state.scan_enabled = False
                        elif line.startswith("OK WATCH=ON"):
                            state.watch_enabled = True
                            state.scan_enabled = False
                            for token in line.split():
                                if token.startswith("FREQ="):
                                    state.watch_freq_mhz = int(token.split("=", 1)[1])
                                if token.startswith("PERIOD_MS="):
                                    state.watch_period_ms = int(token.split("=", 1)[1])
                        elif line.startswith("OK WATCH=OFF"):
                            state.watch_enabled = False
                        elif line.startswith("OK STEP_MHZ="):
                            state.sweep_step_mhz = int(line.rsplit("=", 1)[1])
                        elif line.startswith("OK RSSI_MODE="):
                            state.rssi_mode = line.rsplit("=", 1)[1]
                        if line.startswith("PONG") or line.startswith("OK ") or line.startswith("ERR "):
                            hub.send({"type": "log", "line": line})
                        else:
                            hub.send({"type": "log", "line": line})
                        broadcast_state()

            except Exception as exc:
                state.probe_connected = False
                state.scan_enabled = False
                state.watch_enabled = False
                state.probe_error = f"{type(exc).__name__}: {exc}"
                broadcast_state()
                time.sleep(1.5)


class MockWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.sweep = 0
        self.scanning = True
        self.watching = False
        self.watch_freq = 2453
        self.watch_period = 20
        self.start_ms = time.monotonic()
        self.watch_seq = 0

    def command(self, cmd: str):
        if cmd == "SCAN START":
            self.scanning, self.watching = True, False
            state.scan_enabled, state.watch_enabled = True, False
        elif cmd == "SCAN STOP":
            self.scanning = False
            state.scan_enabled = False
        elif cmd.startswith("WATCH START"):
            p = cmd.split()
            self.watch_freq = int(p[2])
            self.watch_period = int(p[3]) if len(p) > 3 else 20
            self.watching, self.scanning = True, False
            state.watch_enabled, state.scan_enabled = True, False
            state.watch_freq_mhz, state.watch_period_ms = self.watch_freq, self.watch_period
        elif cmd == "WATCH STOP":
            self.watching = False
            state.watch_enabled = False
        elif cmd.startswith("STEP "):
            state.sweep_step_mhz = int(cmd.split()[1])
        elif cmd.startswith("RSSI MODE "):
            state.rssi_mode = cmd.split()[2].upper()
        broadcast_state()

    def run(self):
        state.probe_connected = True
        state.probe_port = "MOCK"
        state.probe_product = "OpenVusion RF Probe MOCK"
        state.probe_serial = "MOCK"
        state.firmware = "OpenVusion_RF_Probe_v0.7.0_MOCK"
        state.scan_enabled = True
        broadcast_state()
        while not self.stop_event.is_set():
            if self.watching:
                self.watch_seq += 1
                t = time.monotonic() - self.start_ms
                pulse = 35 if int(t * 4) % 13 in (0, 1) else 0
                rssi = int(max(-110, min(-30, random.gauss(-99, 2) + pulse)))
                register_watch({
                    "type": "watch",
                    "host_time": datetime.now().isoformat(timespec="milliseconds"),
                    "seq": self.watch_seq,
                    "device_ms": int(t * 1000),
                    "freq_mhz": self.watch_freq,
                    "rssi_dbm": rssi,
                    "rssi_mode": state.rssi_mode,
                })
                time.sleep(max(0.005, self.watch_period / 1000.0))
                continue
            if not self.scanning:
                time.sleep(0.1)
                continue
            self.sweep += 1
            points = []
            pulse = (self.sweep % 18) in (5, 6)
            step = max(1, state.sweep_step_mhz)
            for freq in range(2400, 2501, step):
                noise = random.gauss(-101, 1.5)
                wifi = 18 * math.exp(-((freq - 2437) ** 2) / (2 * 7.0 ** 2)) if 2420 <= freq <= 2454 else 0
                narrow = 38 * math.exp(-((freq - 2453) ** 2) / (2 * 0.8 ** 2)) if pulse else 0
                rssi = int(max(-110, min(-25, noise + wifi + narrow)))
                points.append({"freq_mhz": freq, "rssi_dbm": rssi})
            register_sweep({
                "type": "sweep",
                "host_time": datetime.now().isoformat(timespec="milliseconds"),
                "sweep": self.sweep,
                "device_ms": int((time.monotonic() - self.start_ms) * 1000),
                "points": points,
                "rf_errors": [],
            })
            if self.sweep % 3 == 0:
                register_ble_packet({
                    "type": "packet", "capture_kind": "ble_advertising_report",
                    "capture_level": "MOCK", "protocol": "BLE-ADV",
                    "host_time": datetime.now().isoformat(timespec="milliseconds"),
                    "address": "D2:34:56:78:9A:BC", "name": "Mock Sensor",
                    "local_name": "WF-Mock", "rssi_dbm": int(random.gauss(-56, 3)),
                    "tx_power_dbm": -4,
                    "manufacturer_data": [{"company_id": 0x0059, "company_id_hex": "0x0059", "data_hex": "01020304"}],
                    "service_uuids": ["0000180f-0000-1000-8000-00805f9b34fb"],
                    "service_data": {}, "raw_summary": "MFG[0x0059]=01020304",
                })
            time.sleep(0.45)


probe = MockWorker() if CONFIG.get("mock_mode", False) else ProbeWorker()
nfc = None
ble = None
ble_lock = threading.Lock()


def start_ble_watcher():
    global ble
    bcfg = CONFIG.get("ble_observer", {})
    if not bcfg.get("enabled", False):
        state.ble_enabled = False
        return False, "BLE observer je v configu vypnutý"
    state.ble_enabled = True
    if CONFIG.get("mock_mode", False):
        state.ble_connected = True
        state.ble_mode = "mock"
        return True, "mock"
    with ble_lock:
        if ble is not None and ble.is_alive():
            return True, "already running"
        state.ble_error = ""
        ble = BleWatcher(
            emit_packet=register_ble_packet,
            state_cb=update_ble_state,
            scan_mode=str(bcfg.get("scan_mode", "active")),
            allow_active_fallback=bool(bcfg.get("allow_active_fallback", False)),
            adapter=bcfg.get("adapter") or None,
        )
        ble.start()
    return True, "starting"


def stop_ble_watcher():
    global ble
    with ble_lock:
        if ble is not None:
            ble.stop()
        ble = None
    state.ble_connected = False
    return True

app = FastAPI(title=f"WaterFall v{APP_VERSION}")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    global nfc, ble
    hub.loop = asyncio.get_running_loop()
    probe.start()

    ncfg = CONFIG.get("nfc_reader", {})
    if ncfg.get("enabled", False):
        nfc = NfcWatcher(
            port=ncfg["serial_port"], baudrate=int(ncfg.get("baudrate", 9600)),
            expected_uid=ncfg.get("expected_uid", ""),
            poll_interval_ms=int(ncfg.get("poll_interval_ms", 80)),
            emit=emit_marker, state_cb=update_nfc_state,
        )
        nfc.start()

    bcfg = CONFIG.get("ble_observer", {})
    state.ble_enabled = bool(bcfg.get("enabled", False))
    if state.ble_enabled and bool(bcfg.get("autostart", False)):
        start_ble_watcher()
    elif CONFIG.get("mock_mode", False):
        state.ble_enabled = True

    emit_marker("SERVER_START", f"WaterFall v{APP_VERSION}")
    broadcast_state()




register_routes(app, SimpleNamespace(
    STATIC_DIR=STATIC_DIR, state=state, hub=hub, APP_VERSION=APP_VERSION, pcap=pcap,
    start_ble_watcher=start_ble_watcher, stop_ble_watcher=stop_ble_watcher,
    broadcast_state=broadcast_state, history_lock=history_lock, history=history,
    watch_lock=watch_lock, watch_history=watch_history, rf_event_lock=rf_event_lock,
    rf_event_history=rf_event_history, registry=registry, packet_lock=packet_lock,
    packet_history=packet_history, PACKET_LIMIT=PACKET_LIMIT, probe=probe,
    analyzer_lock=analyzer_lock, analyzer_settings=analyzer_settings, emit_marker=emit_marker,
    csv_writer=csv_writer, events=events, capture=capture, relay=relay, CONFIG=CONFIG,
))
