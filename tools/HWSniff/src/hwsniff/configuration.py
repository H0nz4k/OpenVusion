from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

# BCM GPIO ↔ physical pin (40-pin header, lower block)
GPIO_PHYSICAL: dict[str, int] = {
    "reserve": 29,
    "stop": 31,
    "dip1": 32,
    "dip2": 33,
    "green": 35,
    "yellow": 36,
    "red": 37,
    "blue": 38,
    "start": 40,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "platform": "pi-zero-gpio",
    "hardware_profile": "v2",
    "version": "2.1.0",
    "data_root": "/var/lib/hwsniff",
    "capture_root": "/var/lib/hwsniff/captures",
    "log_root": "/var/log/hwsniff",
    "gpio_prefer_mock": False,
    "gpio": {
        "buttons": {
            "start": 21,
            "stop": 6,
            "active_low": True,
            "pull_up": True,
            "debounce_ms": 50,
            "shutdown_hold_seconds": 3,
            "chord_hold_seconds": 5,
            "chord_warn_seconds": 4,
        },
        "dip": {
            "dip1": 12,
            "dip2": 13,
            "active_low": True,
            "pull_up": True,
        },
        "leds": {
            "green": 19,
            "yellow": 16,
            "red": 26,
            "blue": 20,
            "active_high": True,
        },
    },
    "led_patterns": {
        "slow_ms": 500,
        "fast_ms": 250,
        "single_flash_ms": 150,
        "double_flash_ms": 150,
        "triple_flash_ms": 100,
        "border_ms": 250,
        "heartbeat_period_ms": 3000,
        "heartbeat_pulse_ms": 120,
        "error3_on_ms": 500,
        "error3_off_ms": 500,
        "error3_pause_ms": 1500,
        "count_blink_ms": 500,
        "count_blink_count": 5,
    },
    "timing": {
        "boot_led_ms": 500,
        "boot_cycles": 2,
        "error2_ms": 500,
        "error3_ms": 500,
        "error3_pause_ms": 1500,
        "sweetp_border_ms": 250,
        "read_progress_blink_ms": 250,
        "read_complete_ms": 500,
        "read_complete_count": 5,
        "wlan_period_seconds": 3,
        "wlan_pulse_ms": 120,
        "reader_poll_seconds": 1.0,
    },
    "network": {
        "interface": "wlan0",
        "poll_seconds": 3,
    },
    "upload": {
        "enabled": True,
        "trigger_mode": 2,
        "source_root": "/var/lib/hwsniff/export",
        "state_file": "/var/lib/hwsniff/upload-state.json",
        "server": "ftp.altisima.cz",
        "port": 21,
        "username": "altisimaservis.cz",
        "password": "",
        "remote_dir": "/servis/osobni_slozky/hamouz/tag_exports/",
        "use_tls": False,
        "passive": True,
        "connect_timeout_seconds": 15,
        "rescan_interval_seconds": 10,
        "retry_delays_seconds": [5, 15, 30, 60],
    },
    "self_test": {
        "enabled": True,
        "led_ms": 500,
        "cycles": 2,
    },
    "mock_collector": {
        "work_seconds": 1.2,
        "save_seconds": 0.2,
        "outcome": "SUCCESS",
        "phase_seconds": 0.15,
    },
    "mock_sweet_point": {
        "period_seconds": 1.0,
    },
    "boot": {},
    "shutdown": {
        "enabled": False,
        "command": ["sudo", "systemctl", "poweroff"],
    },
    "service_restart": {
        "marker_path": "/run/hwsniff/service_restart",
    },
    "reader": {
        "auto_detect": True,
        # Prefer Pi GPIO UART alias (symlink → ttyS0/ttyAMA*). USB S/N still works.
        "preferred_serial": "/dev/serial0",
        "scan_interval_seconds": 1.0,
        "handshake_timeout_seconds": 2,
        "reconnect_delay_seconds": 2,
        "retry_count": 3,
        "retry_delay_ms": 150,
        "session_seconds": 2.0,
        "session_interval_ms": 50,
        "raw_trace": True,
        "confirm_reads": 3,
    },
    "collector": {
        "application_samples": 3,
        "session_duration_seconds": 2.0,
        "session_interval_ms": 50,
        "allow_duplicate": True,
        "wait_for_removal": False,
        "minimum_free_space_mb": 256,
        "include_session": True,
        "include_full_dump": True,
        "full_dump_samples": 1,
        "export_bundle_root": "/var/lib/hwsniff/export",
        "export_bundle_mirror_root": "/home/sniffer/exports",
        "include_logs_in_bundle": False,
        "phase_retry_count": 3,
        "phase_retry_delay_ms": 150,
        "tag_acquire_timeout_seconds": 30,
        "capture_timeout_seconds": 180,
        "raw_trace": True,
        "confirm_reads": 3,
        "use_mock": False,
    },
    "display": {
        "fullscreen": True,
        "width": 480,
        "height": 320,
        "rotation": 0,
        "hide_cursor": True,
        "show_debug": False,
    },
    "ui": {
        "success_display_seconds": 1.5,
        "error_display_seconds": 3.0,
        "allow_shutdown_button": True,
    },
    "sweetp": {
        "green_min": 75,
        "yellow_min": 56,
        "borderline_min": 40,
        "borderline_max": 55,
        "hysteresis": 3,
        "read_minimum": 56,
        "sample_interval_ms": 150,
        "window_size": 20,
        "short_window_size": 5,
        "trend_threshold": 5.0,
        "trend_hold_ms": 800,
        "good_quality_threshold": 85.0,
        "poor_quality_threshold": 50.0,
        "good_hold_ms": 3000,
        "min_samples_for_trend": 5,
        "min_samples_for_ok": 8,
        "latency_good_ms": 80.0,
        "latency_bad_ms": 600.0,
        "weight_success": 0.60,
        "weight_latency": 0.25,
        "weight_uid_consistency": 0.15,
        "use_latency": True,
        "ui_update_ms": 150,
        # Live SweetP: SearchTag alone (~450–500 ms). Extra RF commands double latency.
        "require_get_version": False,
        "require_page_00": False,
        "require_application_block": False,
        "probe_attempts": 10,
        "probe_interval_ms": 150,
        "minimum_success_ratio": 0.9,
        "minimum_consecutive_successes": 5,
        "require_stable_uid": True,
        "auto_repeat_seconds": 0.5,
        "use_mock": False,
        # Dual-score UI filters (read-quality, not RF RSSI)
        "fast_alpha": 0.75,
        "stable_alpha": 0.25,
        "trend_window_samples": 3,
        "trend_deadband_points_per_second": 8.0,
        "trend_strong_points_per_second": 40.0,
        "trend_min_blink_interval_ms": 200,
        "trend_max_blink_interval_ms": 1000,
        "trend_pulse_ms": 80,
        "no_tag_confirm_samples": 2,
        "max_trace_samples": 2000,
    },
}

# Alpha1 pin fingerprints — must never be silently treated as v2.
_LEGACY_ALPHA1_PINS = {
    ("buttons", "start"): 17,
    ("buttons", "stop"): 27,
    ("dip", "dip1"): 22,
    ("dip", "dip2"): 18,
    ("leds", "green"): 5,
}


class ConfigError(ValueError):
    """Invalid or incompatible HWSniff configuration."""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _looks_like_legacy_alpha1(document: dict[str, Any]) -> bool:
    if document.get("hardware_profile") == "v2":
        return False
    gpio = document.get("gpio") or {}
    hits = 0
    for (section, key), expected in _LEGACY_ALPHA1_PINS.items():
        if (gpio.get(section) or {}).get(key) == expected:
            hits += 1
    version = str(document.get("version") or "")
    if "alpha1" in version.lower() or version.startswith("1.0"):
        return True
    return hits >= 3


def validate_config(config: dict[str, Any], *, source: dict[str, Any] | None = None) -> None:
    profile = config.get("hardware_profile")
    if profile != "v2":
        raise ConfigError(
            f"Unsupported hardware_profile={profile!r}. "
            "HWSniff v2 requires hardware_profile='v2'. "
            "Install the default config from config/config.gpio.example.json."
        )
    if source is not None and _looks_like_legacy_alpha1(source):
        raise ConfigError(
            "Legacy HWSniff alpha1 GPIO config detected. "
            "v1 pin map must not be used as v2. Replace /etc/hwsniff/config.json "
            "with the v2 example (hardware_profile='v2')."
        )


def load_config(path: Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if path is None:
        validate_config(config)
        return config
    path = Path(path)
    if not path.exists():
        validate_config(config)
        return config
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ConfigError("Config root must be an object")
    validate_config(deep_merge(DEFAULT_CONFIG, document), source=document)
    return deep_merge(config, document)


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
