from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "data_root": "/var/lib/hwsniff",
    "capture_root": "/var/lib/hwsniff/captures",
    "log_root": "/var/log/hwsniff",
    "reader": {
        "auto_detect": True,
        "preferred_serial": None,
        "scan_interval_seconds": 2,
        "handshake_timeout_seconds": 2,
        "reconnect_delay_seconds": 2,
    },
    "collector": {
        "application_samples": 5,
        "full_dump_samples": 0,
        "session_duration_seconds": 2.0,
        "session_interval_ms": 50,
        "allow_duplicate": False,
        "wait_for_removal": True,
        "minimum_free_space_mb": 1024,
        "include_session": True,
        "include_full_dump": False,
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
