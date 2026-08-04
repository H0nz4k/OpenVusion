"""Upload / FTP settings loaded from HWSniff config (never log secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


DEFAULT_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)


@dataclass
class UploadSettings:
    enabled: bool = True
    trigger_mode: int = 2
    source_root: str = "/var/lib/hwsniff/export"
    state_file: str = "/var/lib/hwsniff/upload-state.json"
    server: str = "ftp.altisima.cz"
    port: int = 21
    username: str = "altisimaservis.cz"
    password: str = ""
    remote_dir: str = "/servis/osobni_slozky/hamouz/exprort/"
    use_tls: bool = False
    passive: bool = True
    connect_timeout_seconds: float = 15.0
    rescan_interval_seconds: float = 10.0
    retry_delays_seconds: tuple[float, ...] = DEFAULT_RETRY_DELAYS
    interface: str = "wlan0"
    # Completed export bundle suffixes (HWSniff packs .tar; .zip accepted too)
    bundle_suffixes: tuple[str, ...] = (".tar", ".zip")

    @property
    def password_configured(self) -> bool:
        return bool(self.password.strip())

    def safe_dict(self) -> dict[str, Any]:
        """Config snapshot without password — safe for logs."""
        return {
            "enabled": self.enabled,
            "trigger_mode": self.trigger_mode,
            "source_root": self.source_root,
            "state_file": self.state_file,
            "server": self.server,
            "port": self.port,
            "username": self.username,
            "password_set": self.password_configured,
            "remote_dir": self.remote_dir,
            "use_tls": self.use_tls,
            "passive": self.passive,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "rescan_interval_seconds": self.rescan_interval_seconds,
            "retry_delays_seconds": list(self.retry_delays_seconds),
            "interface": self.interface,
            "bundle_suffixes": list(self.bundle_suffixes),
        }


def load_upload_settings(config: dict[str, Any] | None) -> UploadSettings:
    """Merge upload section + collector.export_bundle_root; password from env."""
    cfg = config or {}
    section = dict(cfg.get("upload") or {})
    coll = cfg.get("collector") or {}
    net = cfg.get("network") or {}

    source = section.get("source_root") or coll.get(
        "export_bundle_root", "/var/lib/hwsniff/export"
    )
    data_root = cfg.get("data_root") or "/var/lib/hwsniff"
    state_file = section.get("state_file") or f"{data_root}/upload-state.json"

    delays_raw = section.get("retry_delays_seconds")
    if isinstance(delays_raw, (list, tuple)) and delays_raw:
        delays = tuple(float(x) for x in delays_raw)
    else:
        delays = DEFAULT_RETRY_DELAYS

    password = str(section.get("password") or "")
    env_pw = os.environ.get("HWSNIFF_FTP_PASSWORD", "")
    if env_pw:
        password = env_pw

    suffixes = section.get("bundle_suffixes")
    if isinstance(suffixes, (list, tuple)) and suffixes:
        bundle_suffixes = tuple(str(s) for s in suffixes)
    else:
        bundle_suffixes = (".tar", ".zip")

    return UploadSettings(
        enabled=bool(section.get("enabled", True)),
        trigger_mode=int(section.get("trigger_mode", 2)),
        source_root=str(source),
        state_file=str(state_file),
        server=str(section.get("server", "ftp.altisima.cz")),
        port=int(section.get("port", 21)),
        username=str(section.get("username", "altisimaservis.cz")),
        password=password,
        remote_dir=str(
            section.get("remote_dir", "/servis/osobni_slozky/hamouz/exprort/")
        ),
        use_tls=bool(section.get("use_tls", False)),
        passive=bool(section.get("passive", True)),
        connect_timeout_seconds=float(
            section.get("connect_timeout_seconds", 15)
        ),
        rescan_interval_seconds=float(
            section.get("rescan_interval_seconds", 10)
        ),
        retry_delays_seconds=delays,
        interface=str(section.get("interface") or net.get("interface", "wlan0")),
        bundle_suffixes=bundle_suffixes,
    )
