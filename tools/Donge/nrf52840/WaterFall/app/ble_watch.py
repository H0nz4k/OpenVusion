from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Callable


class BleWatcher(threading.Thread):
    """
    Optional Bluetooth LE observer using the Raspberry Pi/host Bluetooth radio.

    This intentionally does not use the nRF52840 RF Probe radio. The reason is
    physical: a single radio cannot continuously sweep 2400..2500 MHz and at the
    same time follow BLE advertisements/connections. Using the Pi controller lets
    WaterFall keep spectrum survey and BLE inventory live concurrently.

    Passive mode is requested by default. If BlueZ/Bleak does not support it,
    WaterFall reports the error instead of silently switching to active scanning,
    unless allow_active_fallback=true is explicitly configured.
    """

    def __init__(
        self,
        emit_packet: Callable[[dict], None],
        state_cb: Callable[[bool, str, str], None],
        scan_mode: str = "passive",
        allow_active_fallback: bool = False,
        adapter: str | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.emit_packet = emit_packet
        self.state_cb = state_cb
        self.scan_mode = scan_mode
        self.allow_active_fallback = allow_active_fallback
        self.adapter = adapter
        self.stop_event = threading.Event()

    @staticmethod
    def _packet(device, ad) -> dict:
        mfg = []
        for company_id, payload in (getattr(ad, "manufacturer_data", {}) or {}).items():
            mfg.append({
                "company_id": int(company_id),
                "company_id_hex": f"0x{int(company_id):04X}",
                "data_hex": bytes(payload).hex().upper(),
            })

        service_data = {
            str(k): bytes(v).hex().upper()
            for k, v in (getattr(ad, "service_data", {}) or {}).items()
        }
        service_uuids = [str(v) for v in (getattr(ad, "service_uuids", []) or [])]

        rssi = getattr(ad, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)

        raw_parts = []
        for item in mfg:
            raw_parts.append(f"MFG[{item['company_id_hex']}]={item['data_hex']}")
        for k, v in service_data.items():
            raw_parts.append(f"SVC[{k}]={v}")

        return {
            "type": "packet",
            "capture_kind": "ble_advertising_report",
            "capture_level": "BlueZ advertising report (not raw Link Layer PDU)",
            "protocol": "BLE-ADV",
            "host_time": datetime.now().isoformat(timespec="milliseconds"),
            "address": str(getattr(device, "address", "") or ""),
            "name": str(getattr(device, "name", "") or ""),
            "local_name": str(getattr(ad, "local_name", "") or ""),
            "rssi_dbm": int(rssi) if rssi is not None else None,
            "tx_power_dbm": getattr(ad, "tx_power", None),
            "manufacturer_data": mfg,
            "service_uuids": service_uuids,
            "service_data": service_data,
            "raw_summary": "; ".join(raw_parts),
        }

    async def _run_scanner(self, mode: str) -> None:
        from bleak import BleakScanner

        def detected(device, advertisement_data):
            try:
                self.emit_packet(self._packet(device, advertisement_data))
            except Exception:
                # Scanner callback must stay resilient; malformed optional data
                # must not stop RF acquisition.
                return

        kwargs = {"detection_callback": detected}
        if mode:
            kwargs["scanning_mode"] = mode
        if self.adapter:
            # Current Bleak uses the BlueZ-specific argument dictionary.
            kwargs["bluez"] = {"adapter": self.adapter}

        scanner = BleakScanner(**kwargs)
        await scanner.start()
        self.state_cb(True, "", mode)
        try:
            while not self.stop_event.is_set():
                await asyncio.sleep(0.25)
        finally:
            await scanner.stop()

    def run(self) -> None:
        try:
            asyncio.run(self._run_scanner(self.scan_mode))
            self.state_cb(False, "", self.scan_mode)
            return
        except Exception as exc:
            first_error = f"{type(exc).__name__}: {exc}"

        if self.scan_mode == "passive" and self.allow_active_fallback and not self.stop_event.is_set():
            try:
                self.state_cb(False, first_error + " — zkouším explicitně povolený active fallback", "passive")
                asyncio.run(self._run_scanner("active"))
                return
            except Exception as exc:
                self.state_cb(False, f"{first_error}; active fallback: {type(exc).__name__}: {exc}", "")
                return

        self.state_cb(False, first_error, self.scan_mode)

    def stop(self) -> None:
        self.stop_event.set()
