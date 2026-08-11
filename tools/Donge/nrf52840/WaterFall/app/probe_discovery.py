from __future__ import annotations

from serial.tools import list_ports

def parse_vid_pid(value, default):
    if value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value), 16)


def discover_probe(cfg):
    requested = str(cfg.get("serial_port", "auto"))
    if requested and requested.lower() != "auto":
        return {"device": requested, "product": "", "serial_number": ""}

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
            f"{p.device}:{p.product or p.description}:{p.serial_number}" for p in matches
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
