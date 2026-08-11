from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from .rf_analysis import frequency_labels


def register_routes(app, d):
    STATIC_DIR = d.STATIC_DIR
    state = d.state
    hub = d.hub
    APP_VERSION = d.APP_VERSION
    pcap = d.pcap
    start_ble_watcher = d.start_ble_watcher
    stop_ble_watcher = d.stop_ble_watcher
    broadcast_state = d.broadcast_state
    history_lock = d.history_lock
    history = d.history
    watch_lock = d.watch_lock
    watch_history = d.watch_history
    rf_event_lock = d.rf_event_lock
    rf_event_history = d.rf_event_history
    registry = d.registry
    packet_lock = d.packet_lock
    packet_history = d.packet_history
    PACKET_LIMIT = d.PACKET_LIMIT
    probe = d.probe
    analyzer_lock = d.analyzer_lock
    analyzer_settings = d.analyzer_settings
    emit_marker = d.emit_marker
    csv_writer = d.csv_writer
    events = d.events
    capture = d.capture
    relay = d.relay
    CONFIG = d.CONFIG

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")


    @app.get("/api/state")
    async def api_state():
        return JSONResponse(asdict(state))


    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "version": APP_VERSION,
            "probe_connected": state.probe_connected,
            "sweep_count": state.sweep_count,
            "ble_connected": state.ble_connected,
            "tshark_available": state.tshark_available,
        }


    @app.get("/api/capabilities")
    async def capabilities():
        return {
            "nrf52840": {
                "survey": True,
                "focused_rssi_watch": True,
                "packet_decoder_in_custom_probe": False,
                "note": (
                    "OpenVusion RF Probe měří RSSI/energy. Jediný nRF52840 radio nemůže současně "
                    "sweepovat celé pásmo a sledovat libovolný packet-level protokol."
                ),
            },
            "ble_observer": {
                "enabled": state.ble_enabled,
                "source": "Raspberry Pi / host Bluetooth via BlueZ/Bleak",
                "capture_level": "advertising reports, not raw Link Layer PDUs",
            },
            "pcap": {
                "tshark_available": state.tshark_available,
                "supported": ["pcap", "pcapng", "cap"],
                "note": "Plný packet decode je dostupný pro importované sniffer capture soubory přes tshark.",
            },
        }


    @app.post("/api/ble/{action}")
    async def ble_action(action: str):
        if action == "start":
            ok, message = start_ble_watcher()
            broadcast_state()
            return {"ok": ok, "message": message}
        if action == "stop":
            stop_ble_watcher()
            broadcast_state()
            return {"ok": True}
        return JSONResponse({"ok": False, "error": "action musí být start|stop"}, status_code=404)


    @app.get("/api/history")
    async def api_history():
        with history_lock:
            return JSONResponse(list(history))


    @app.get("/api/watch/history")
    async def api_watch_history():
        with watch_lock:
            return JSONResponse(list(watch_history))


    @app.get("/api/rf/events")
    async def api_rf_events():
        with rf_event_lock:
            return JSONResponse(list(rf_event_history))


    @app.get("/api/devices")
    async def api_devices():
        return JSONResponse(registry.list())


    @app.get("/api/devices/{device_id:path}")
    async def api_device(device_id: str):
        d = registry.get(device_id)
        if not d:
            return JSONResponse({"ok": False, "error": "device not found"}, status_code=404)
        return JSONResponse(d)


    @app.get("/api/packets")
    async def api_packets(limit: int = 500):
        limit = max(1, min(int(limit), PACKET_LIMIT))
        with packet_lock:
            return JSONResponse(list(packet_history)[-limit:])


    @app.post("/api/command/{command}")
    async def command(command: str):
        mapping = {
            "scan_start": "SCAN START", "scan_stop": "SCAN STOP",
            "once": "ONCE", "ping": "PING", "info": "INFO",
            "watch_stop": "WATCH STOP",
        }
        if command not in mapping:
            return JSONResponse({"ok": False, "error": "unknown command"}, status_code=404)
        probe.command(mapping[command])
        return {"ok": True}


    @app.post("/api/range/{first}/{last}")
    async def set_range(first: int, last: int):
        if not (0 <= first <= last <= 100):
            return JSONResponse({"ok": False, "error": "0 <= first <= last <= 100"}, status_code=400)
        probe.command(f"RANGE {first} {last}")
        return {"ok": True, "first": first, "last": last}


    @app.post("/api/dwell/{ms}")
    async def set_dwell(ms: int):
        if not (1 <= ms <= 100):
            return JSONResponse({"ok": False, "error": "dwell musí být 1..100 ms"}, status_code=400)
        probe.command(f"DWELL {ms}")
        return {"ok": True, "ms": ms}


    @app.post("/api/step/{mhz}")
    async def set_step(mhz: int):
        if mhz not in (1, 2, 5, 10):
            return JSONResponse({"ok": False, "error": "step musí být 1, 2, 5 nebo 10 MHz"}, status_code=400)
        probe.command(f"STEP {mhz}")
        return {"ok": True, "mhz": mhz}


    @app.post("/api/rssi-mode/{mode}")
    async def set_rssi_mode(mode: str):
        mode = mode.upper()
        if mode not in {"LAST", "MAX", "AVG"}:
            return JSONResponse({"ok": False, "error": "mode: LAST|MAX|AVG"}, status_code=400)
        probe.command(f"RSSI MODE {mode}")
        return {"ok": True, "mode": mode}


    @app.post("/api/watch/start/{freq_mhz}/{period_ms}")
    async def watch_start(freq_mhz: int, period_ms: int):
        if not (2400 <= freq_mhz <= 2500):
            return JSONResponse({"ok": False, "error": "freq 2400..2500 MHz"}, status_code=400)
        if not (5 <= period_ms <= 5000):
            return JSONResponse({"ok": False, "error": "period 5..5000 ms"}, status_code=400)
        with watch_lock:
            watch_history.clear()
        probe.command(f"WATCH START {freq_mhz} {period_ms}")
        emit_marker("RF_WATCH_START", f"{freq_mhz} MHz / {period_ms} ms", "WEB")
        return {"ok": True, "freq_mhz": freq_mhz, "period_ms": period_ms}


    @app.get("/api/frequency/{freq_mhz}")
    async def frequency_info(freq_mhz: int):
        if not (2400 <= freq_mhz <= 2500):
            return JSONResponse({"ok": False, "error": "freq 2400..2500 MHz"}, status_code=400)
        return {"freq_mhz": freq_mhz, "labels": frequency_labels(freq_mhz)}


    @app.get("/api/analyzer/settings")
    async def analyzer_get():
        with analyzer_lock:
            return JSONResponse(dict(analyzer_settings))


    @app.post("/api/analyzer/settings")
    async def analyzer_set(request: Request):
        data = await request.json()
        try:
            threshold = float(data.get("threshold_above_median_db", analyzer_settings["threshold_above_median_db"]))
            floor = int(data.get("absolute_floor_dbm", analyzer_settings["absolute_floor_dbm"]))
            gap = int(data.get("max_gap_mhz", analyzer_settings["max_gap_mhz"]))
            min_bins = int(data.get("min_bins", analyzer_settings["min_bins"]))
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid values"}, status_code=400)
        if not (1 <= threshold <= 60 and -120 <= floor <= -20 and 1 <= gap <= 10 and 1 <= min_bins <= 20):
            return JSONResponse({"ok": False, "error": "settings out of range"}, status_code=400)
        with analyzer_lock:
            analyzer_settings.update({
                "threshold_above_median_db": threshold,
                "absolute_floor_dbm": floor,
                "max_gap_mhz": gap,
                "min_bins": min_bins,
            })
        emit_marker("ANALYZER_SETTINGS", "RF analyzer settings changed", "WEB", **analyzer_settings)
        return {"ok": True, "settings": analyzer_settings}


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


    @app.post("/api/capture/start")
    async def capture_start(request: Request):
        data = await request.json()
        info = capture.start(str(data.get("label", "")), str(data.get("notes", "")))
        state.capture_active = True
        state.capture_session_id = info.session_id
        state.capture_zip = ""
        emit_marker("CAPTURE_START", info.session_id, "WEB", capture_label=info.label)
        broadcast_state()
        return {"ok": True, "session": asdict(info)}


    @app.post("/api/capture/stop")
    async def capture_stop():
        emit_marker("CAPTURE_STOP", state.capture_session_id or "manual", "WEB")
        info = capture.stop()
        state.capture_active = False
        if info:
            state.capture_zip = info.zip_file
        broadcast_state()
        return {"ok": True, "session": asdict(info) if info else None}


    @app.get("/api/capture/download")
    async def capture_download():
        p = capture.latest_zip()
        if not p:
            return JSONResponse({"ok": False, "error": "capture bundle zatím neexistuje"}, status_code=404)
        return FileResponse(p, filename=p.name)


    @app.get("/api/capture")
    async def capture_list():
        return {"ok": True, "sessions": capture.list_sessions()}


    @app.get("/api/capture/{session_id}/stream/{stream}")
    async def capture_stream(session_id: str, stream: str, limit: int = 1000):
        try:
            rows = capture.read_stream(session_id, stream, limit=limit)
            return {"ok": True, "session_id": session_id, "stream": stream, "rows": rows, "count": len(rows)}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)


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
            return JSONResponse({"ok": False, "error": relay.status.error if relay else "relay unavailable"}, status_code=503)
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


    @app.get("/api/pcap")
    async def pcap_list():
        return {"ok": True, "tshark_available": pcap.available, "files": pcap.list_files()}


    @app.post("/api/pcap/upload")
    async def pcap_upload(request: Request, filename: str = "capture.pcapng"):
        data = await request.body()
        if not data:
            return JSONResponse({"ok": False, "error": "empty upload"}, status_code=400)
        max_size = int(CONFIG.get("pcap_max_upload_mb", 100)) * 1024 * 1024
        if len(data) > max_size:
            return JSONResponse({"ok": False, "error": "capture file too large"}, status_code=413)
        try:
            path = pcap.save_upload(filename, data)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        emit_marker("PCAP_IMPORT", path.name, "WEB", size=len(data))
        return {"ok": True, "name": path.name, "size": len(data)}


    @app.get("/api/pcap/{filename}/summary")
    async def pcap_summary(filename: str, limit: int = 500, display_filter: str = ""):
        try:
            rows = pcap.summary(filename, limit=limit, display_filter=display_filter)
            return {"ok": True, "rows": rows, "count": len(rows)}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


    @app.get("/api/pcap/{filename}/frame/{frame_number}")
    async def pcap_detail(filename: str, frame_number: int):
        try:
            return {"ok": True, **pcap.detail(filename, frame_number)}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


    @app.get("/api/pcap/{filename}/download")
    async def pcap_download(filename: str):
        try:
            path = pcap.resolve(filename)
            return FileResponse(path, filename=path.name)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)


    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await hub.connect(ws)
        await ws.send_json({"type": "state", "state": asdict(state)})
        with history_lock:
            if history:
                await ws.send_json({"type": "history", "sweeps": list(history)})
        with watch_lock:
            if watch_history:
                await ws.send_json({"type": "watch_history", "samples": list(watch_history)})
        with packet_lock:
            if packet_history:
                await ws.send_json({"type": "packet_history", "packets": list(packet_history)})
        await ws.send_json({"type": "devices", "devices": registry.list()})
        with rf_event_lock:
            if rf_event_history:
                await ws.send_json({"type": "rf_event_history", "events": list(rf_event_history)})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(ws)
        except Exception:
            hub.disconnect(ws)
