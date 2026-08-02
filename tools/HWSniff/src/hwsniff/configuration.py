from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "platform": "pi-zero-gpio",
    "version": "1.0-alpha1",
    "data_root": "/var/lib/hwsniff",
    "capture_root": "/var/lib/hwsniff/captures",
    "log_root": "/var/log/hwsniff",
    "gpio_prefer_mock": False,
    "gpio": {
        "buttons": {
            "start": 17,
            "stop": 27,
            "active_low": True,
            "pull_up": True,
            "debounce_ms": 50,
            "shutdown_hold_seconds": 4,
        },
        "dip": {
            "dip1": 22,
            "dip2": 18,
            "active_low": True,
            "pull_up": True,
        },
        "leds": {
            "green": 5,
            "yellow": 6,
            "red": 12,
            "blue": 13,
            "orange": 19,
            "active_high": True,
        },
    },
    "led_patterns": {
        "slow_ms": 500,
        "fast_ms": 100,
        "double_flash_ms": 150,
        "triple_flash_ms": 100,
    },
    "network": {
        "interface": "wlan0",
        "poll_seconds": 3,
    },
    "self_test": {
        "enabled": True,
        "led_ms": 180,
    },
    "mock_collector": {
        "work_seconds": 2.0,
        "save_seconds": 0.3,
        "outcome": "SUCCESS",
    },
    "shutdown": {
        "command": ["systemctl", "poweroff"],
    },
    "reader": {
        "auto_detect": True,
        "preferred_serial": None,
        "scan_interval_seconds": 2,
        "handshake_timeout_seconds": 2,
        "reconnect_delay_seconds": 2,
    },
    "collector": {
        "application_samples": 3,
        "session_duration_seconds": 2.0,
        "session_interval_ms": 50,
        "allow_duplicate": False,
        "wait_for_removal": False,
        "minimum_free_space_mb": 1024,
        "include_session": True,
        "include_full_dump": True,
        "full_dump_samples": 1,
        "export_bundle_root": "/home/sniffer/capture",
        "phase_retry_count": 3,
        "phase_retry_delay_ms": 150,
        "tag_acquire_timeout_seconds": 60,
        "capture_timeout_seconds": 120,
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
        "require_get_version": True,
        "require_page_00": False,
        "require_application_block": False,
        # Legacy keys (ignored by live loop, kept for older configs).
        "probe_attempts": 10,
        "probe_interval_ms": 150,
        "minimum_success_ratio": 0.9,
        "minimum_consecutive_successes": 5,
        "require_stable_uid": True,
        "auto_repeat_seconds": 0.5,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if path is None:
        return config
    path = Path(path)
    if not path.exists():
        return config
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Config root must be an object")
    return deep_merge(config, document)


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
