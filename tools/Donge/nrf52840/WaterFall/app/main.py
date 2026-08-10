from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import random
import statistics
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .events import EventRecorder
from .nfc_watch import NfcWatcher
from .relay import RelayController


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
CONFIG_PATH = Path(os.environ.get("WATERFALL_CONFIG", os.environ.get("OPENVUSION_RF_CONFIG", BASE_DIR / "config.json")))


def load_config():
    if not CONFIG_PATH.exists():
        example = BASE_DIR / "config.example.json"
        if example.exists():
            return json.loads(example.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Config nenalezen: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


CONFIG = load_config()
HISTORY_LIMIT = max(30, int(CONFIG.get("history_sweeps", 240)))


@dataclass
class State:
    probe_connected: bool = False
    probe_port: str = ""
    probe_product: str = ""
    probe_serial: str = ""
    probe_error: str = ""
    firmware: str = ""
    scan_enabled: bool = False
    nfc_connected: bool = False
    nfc_error: str = ""
    nfc_present: bool = False
    nfc_uid: str = ""
    relay_available: bool = False
    relay_power_on: bool = False
    sweep_count: int = 0
    recording: bool = False
    recording_file: str = ""
    experiment_recording: bool = False
    experiment_file: str = ""
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
    def __init__(self, directory):
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
            self.path = self.directory / f"vusion_rf_{stamp}.csv"
            self.fp = self.path.open("w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.fp)
            self.writer.writerow([
                "host_time",
                "sweep",
                "device_ms",
                "freq_mhz",
                "rssi_dbm",
                "peak_freq_mhz",
                "peak_rssi_dbm",
                "median_dbm",
                "mean_dbm",
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

    def write(self, sweep):
        with self.lock:
            if not self.writer:
                return

            summary = sweep.get("summary", {})
            for p in sweep["points"]:
                self.writer.writerow([
                    sweep["host_time"],
                    sweep["sweep"],
                    sweep["device_ms"],
                    p["freq_mhz"],
                    p["rssi_dbm"],
                    summary.get("peak_freq_mhz", ""),
                    summary.get("peak_rssi_dbm", ""),
                    summary.get("median_dbm", ""),
                    summary.get("mean_dbm", ""),
                ])
            self.fp.flush()


hub = Hub()
state = State(mock_mode=bool(CONFIG.get("mock_mode", False)))
csv_writer = CsvWriter(CONFIG["csv_dir"])
events = EventRecorder(CONFIG["experiment_dir"])
history = deque(maxlen=HISTORY_LIMIT)
history_lock = threading.Lock()

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


def emit_marker(kind, label, source="SERVER", **data):
    marker = events.emit(kind, label, source, **data)
    hub.send({"type": "marker", "marker": asdict(marker)})
    return marker


def update_nfc_state(connected, error, present, uid):
    state.nfc_connected = bool(connected)
    state.nfc_error = error or ""
    state.nfc_present = bool(present)
    state.nfc_uid = uid or ""
    broadcast_state()


def summarize_points(points):
    values = [p["rssi_dbm"] for p in points]
    if not values:
        return {}

    peak = max(points, key=lambda p: p["rssi_dbm"])
    med = statistics.median(values)
    mean = statistics.fmean(values)
    ordered = sorted(values)
    p90_idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.9) - 1))

    return {
        "peak_freq_mhz": peak["freq_mhz"],
        "peak_rssi_dbm": peak["rssi_dbm"],
        "median_dbm": round(med, 2),
        "mean_dbm": round(mean, 2),
        "p90_dbm": ordered[p90_idx],
        "min_dbm": min(values),
        "max_dbm": max(values),
        "dynamic_range_db": round(max(values) - min(values), 2),
        "bins": len(values),
        "above_median_10db": sum(1 for v in values if v >= med + 10),
        "above_median_20db": sum(1 for v in values if v >= med + 20),
    }


def register_sweep(sweep):
    sweep["summary"] = summarize_points(sweep["points"])

    with history_lock:
        history.append(sweep)

    state.sweep_count = int(sweep["sweep"])
    state.last_rx_iso = sweep["host_time"]
    csv_writer.write(sweep)
    hub.send(sweep)


def parse_vid_pid(value, default):
    if value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value), 16)


def discover_probe(cfg):
    requested = str(cfg.get("serial_port", "auto"))

    if requested and requested.lower() != "auto":
        return {
            "device": requested,
            "product": "",
            "serial_number": "",
        }

    vid = parse_vid_pid(cfg.get("vid"), 0x2FE3)
    pid = parse_vid_pid(cfg.get("pid"), 0x0001)
    product_prefix = str(cfg.get("product_prefix", "OpenVusion RF Probe"))
    wanted_serial = str(cfg.get("serial_number", "")).strip()

    matches = []
    for p in list_ports.comports():
        if p.vid != vid or p.pid != pid:
            continue
        if product_prefix and not (p.product or p.description or "").startswith(product_prefix):
            continue
        if wanted_serial and (p.serial_number or "") != wanted_serial:
            continue
        matches.append(p)

    if len(matches) != 1:
        desc = ", ".join(
            f"{p.device}:{p.product or p.description}:{p.serial_number}"
            for p in matches
        ) or "žádný"
        raise RuntimeError(
            f"RF probe auto-detect očekává 1 zařízení {vid:04x}:{pid:04x}, "
            f"nalezeno {len(matches)} ({desc})"
        )

    p = matches[0]
    return {
        "device": p.device,
        "product": p.product or p.description or "",
        "serial_number": p.serial_number or "",
    }


class ProbeWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q = deque()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    def command(self, value):
        with self.lock:
            self.q.append(value)

    def commands(self):
        out = []
        with self.lock:
            while self.q:
                out.append(self.q.popleft())
        return out

    @staticmethod
    def parse(line):
        if not line.startswith("SWEEP,"):
            return None

        try:
            parts = line.split(",")
            if len(parts) < 4:
                return None

            points = []
            errors = []

            for item in parts[3:]:
                if ":" not in item:
                    continue
                f, r = item.split(":", 1)
                freq = int(f)
                if r.startswith("ERR"):
                    errors.append({"freq_mhz": freq, "error": r})
                    continue
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

    def _send(self, ser, cmd):
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()

        if cmd == "SCAN START":
            state.scan_enabled = True
        elif cmd == "SCAN STOP":
            state.scan_enabled = False

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
                    emit_marker(
                        "RF_PROBE_ONLINE",
                        f"{port} {found['product']}".strip(),
                        "NRF52840",
                        serial=found["serial_number"],
                    )

                    # v0.6.1 does not send an unsolicited banner.
                    self._send(ser, "PING")
                    time.sleep(0.05)
                    self._send(ser, "INFO")

                    if cfg.get("auto_scan", True):
                        time.sleep(0.15)
                        self._send(ser, "SCAN START")
                        broadcast_state()

                    while not self.stop_event.is_set():
                        for cmd in self.commands():
                            self._send(ser, cmd)
                            broadcast_state()

                        raw = ser.readline()
                        if not raw:
                            continue

                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        state.last_line = line

                        sweep = self.parse(line)
                        if sweep:
                            register_sweep(sweep)
                            continue

                        if line.startswith("FW="):
                            state.firmware = line[3:]
                            broadcast_state()
                        elif line.startswith("PONG"):
                            hub.send({"type": "log", "line": line})
                        elif line.startswith("OK SCAN=ON"):
                            state.scan_enabled = True
                            broadcast_state()
                            hub.send({"type": "log", "line": line})
                        elif line.startswith("OK SCAN=OFF"):
                            state.scan_enabled = False
                            broadcast_state()
                            hub.send({"type": "log", "line": line})
                        else:
                            hub.send({"type": "log", "line": line})

            except Exception as exc:
                state.probe_connected = False
                state.scan_enabled = False
                state.probe_error = f"{type(exc).__name__}: {exc}"
                broadcast_state()
                time.sleep(1.5)


class MockWorker(threading.Thread):
    """UI/demo mode without hardware."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.sweep = 0
        self.scanning = True
        self.start_ms = time.monotonic()

    def run(self):
        state.probe_connected = True
        state.probe_port = "MOCK"
        state.probe_product = "OpenVusion RF Probe MOCK"
        state.probe_serial = "MOCK"
        state.firmware = "OpenVusion_RF_Probe_MOCK"
        state.scan_enabled = True
        broadcast_state()

        while not self.stop_event.is_set():
            if not self.scanning:
                time.sleep(0.1)
                continue

            self.sweep += 1
            points = []
            pulse = (self.sweep % 18) in (5, 6)
            for freq in range(2400, 2501):
                noise = random.gauss(-101, 1.5)
                wifi = 0.0
                if 2426 <= freq <= 2448:
                    wifi = 18 * math.exp(-((freq - 2437) ** 2) / (2 * 7.0 ** 2))
                narrow = 0.0
                if pulse:
                    narrow = 38 * math.exp(-((freq - 2453) ** 2) / (2 * 0.8 ** 2))
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
            time.sleep(0.45)


probe = MockWorker() if CONFIG.get("mock_mode", False) else ProbeWorker()
nfc = None


app = FastAPI(title="WaterFall v0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    global nfc
    hub.loop = asyncio.get_running_loop()
    probe.start()

    ncfg = CONFIG.get("nfc_reader", {})
    if ncfg.get("enabled", False):
        nfc = NfcWatcher(
            port=ncfg["serial_port"],
            baudrate=int(ncfg.get("baudrate", 9600)),
            expected_uid=ncfg.get("expected_uid", ""),
            poll_interval_ms=int(ncfg.get("poll_interval_ms", 80)),
            emit=emit_marker,
            state_cb=update_nfc_state,
        )
        nfc.start()

    emit_marker("SERVER_START", "WaterFall v0.3.0")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
async def api_state():
    return JSONResponse(asdict(state))


@app.get("/api/history")
async def api_history():
    with history_lock:
        return JSONResponse(list(history))


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": "0.3.0",
        "probe_connected": state.probe_connected,
        "sweep_count": state.sweep_count,
    }


@app.post("/api/command/{command}")
async def command(command: str):
    mapping = {
        "scan_start": "SCAN START",
        "scan_stop": "SCAN STOP",
        "once": "ONCE",
        "ping": "PING",
        "info": "INFO",
    }
    if command not in mapping:
        return JSONResponse({"ok": False, "error": "unknown command"}, status_code=404)

    if isinstance(probe, MockWorker):
        if command == "scan_start":
            probe.scanning = True
            state.scan_enabled = True
        elif command == "scan_stop":
            probe.scanning = False
            state.scan_enabled = False
        broadcast_state()
    else:
        probe.command(mapping[command])

    return {"ok": True}


@app.post("/api/range/{first}/{last}")
async def set_range(first: int, last: int):
    if not (0 <= first <= last <= 100):
        return JSONResponse(
            {"ok": False, "error": "range musí splňovat 0 <= first <= last <= 100"},
            status_code=400,
        )
    if isinstance(probe, ProbeWorker):
        probe.command(f"RANGE {first} {last}")
    return {"ok": True, "first": first, "last": last}


@app.post("/api/dwell/{ms}")
async def set_dwell(ms: int):
    if not (1 <= ms <= 100):
        return JSONResponse(
            {"ok": False, "error": "dwell musí být 1..100 ms"},
            status_code=400,
        )
    if isinstance(probe, ProbeWorker):
        probe.command(f"DWELL {ms}")
    return {"ok": True, "ms": ms}


@app.post("/api/record/start")
async def rec_start():
    path = csv_writer.start()
    state.recording = True
    state.recording_file = path
    emit_marker("RF_RECORD_START", Path(path).name, "WEB")
    await hub.broadcast({"type": "state", "state": asdict(state)})
    return {"ok": True, "path": path}


@app.post("/api/record/stop")
async def rec_stop():
    csv_writer.stop()
    emit_marker("RF_RECORD_STOP", Path(state.recording_file).name if state.recording_file else "", "WEB")
    state.recording = False
    await hub.broadcast({"type": "state", "state": asdict(state)})
    return {"ok": True, "path": state.recording_file}


@app.get("/api/record/download")
async def rec_download():
    p = Path(state.recording_file)
    if not state.recording_file or not p.exists():
        return JSONResponse({"ok": False, "error": "CSV zatím neexistuje"}, status_code=404)
    return FileResponse(p, filename=p.name)


@app.post("/api/experiment/start")
async def exp_start():
    path = events.start()
    state.experiment_recording = True
    state.experiment_file = path
    emit_marker("EXPERIMENT_START", Path(path).name)
    await hub.broadcast({"type": "state", "state": asdict(state)})
    return {"ok": True, "path": path}


@app.post("/api/experiment/stop")
async def exp_stop():
    emit_marker("EXPERIMENT_STOP", "manual")
    events.stop()
    state.experiment_recording = False
    await hub.broadcast({"type": "state", "state": asdict(state)})
    return {"ok": True, "path": state.experiment_file}


@app.get("/api/experiment/download")
async def exp_download():
    p = Path(state.experiment_file)
    if not state.experiment_file or not p.exists():
        return JSONResponse({"ok": False, "error": "experiment JSONL zatím neexistuje"}, status_code=404)
    return FileResponse(p, filename=p.name)


@app.post("/api/marker/{label}")
async def marker(label: str):
    emit_marker("USER_MARKER", label, "WEB")
    return {"ok": True}


@app.post("/api/relay/{action}")
async def relay_action(action: str):
    if not relay or not relay.status.available:
        return JSONResponse(
            {
                "ok": False,
                "error": relay.status.error if relay else "relay unavailable",
            },
            status_code=503,
        )

    if action == "on":
        relay.set_power(True)
        state.relay_power_on = True
        emit_marker("POWER_ON", "VUSION POWER ON", "GPIO", gpio=relay.gpio_bcm)
    elif action == "off":
        relay.set_power(False)
        state.relay_power_on = False
        emit_marker("POWER_OFF", "VUSION POWER OFF", "GPIO", gpio=relay.gpio_bcm)
    else:
        return JSONResponse({"ok": False, "error": "unknown relay action"}, status_code=404)

    await hub.broadcast({"type": "state", "state": asdict(state)})
    return {"ok": True, "power_on": state.relay_power_on}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    await ws.send_json({"type": "state", "state": asdict(state)})

    with history_lock:
        if history:
            await ws.send_json({"type": "history", "sweeps": list(history)})

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)
