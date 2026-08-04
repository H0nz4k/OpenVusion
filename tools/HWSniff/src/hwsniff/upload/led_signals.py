"""Non-blocking LED level generators for upload mode (max one of G/Y/R on)."""

from __future__ import annotations

from enum import Enum


class UploadLedPattern(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"  # G → Y → R chase
    SUCCESS = "success"  # green solid 2s + 3 blinks
    EMPTY = "empty"  # yellow double ×3
    NO_WIFI = "no_wifi"  # blue triple + pause
    FTP_ERROR = "ftp_error"  # red triple + pause
    PARTIAL = "partial"  # Y/R alternate ×3 then idle chase later


def led_levels(
    pattern: UploadLedPattern,
    elapsed_s: float,
    *,
    step_ms: float = 200.0,
) -> dict[str, bool]:
    """Return desired ON levels for green/yellow/red/blue."""
    g = y = r = b = False
    step = max(0.05, step_ms / 1000.0)

    if pattern == UploadLedPattern.IDLE:
        pass
    elif pattern == UploadLedPattern.ACTIVE:
        phase = int(elapsed_s / step) % 3
        g = phase == 0
        y = phase == 1
        r = phase == 2
    elif pattern == UploadLedPattern.SUCCESS:
        # 0–2s solid green; then 3 blinks (on/off 150ms); then off
        if elapsed_s < 2.0:
            g = True
        else:
            t = elapsed_s - 2.0
            blink = 0.15
            # 3 × (on + off) = 0.9s
            if t < 0.9:
                slot = int(t / blink)
                g = (slot % 2) == 0
    elif pattern == UploadLedPattern.EMPTY:
        # yellow double blink, pause, ×3
        # one unit: on, off, on, off, pause = 4*0.12 + 0.4
        unit_on = 0.12
        unit_pause = 0.4
        unit = 4 * unit_on + unit_pause
        if elapsed_s < 3 * unit:
            pos = elapsed_s % unit
            if pos < 4 * unit_on:
                y = int(pos / unit_on) % 2 == 0
    elif pattern == UploadLedPattern.NO_WIFI:
        # blue 3× short + long pause
        on_ms = 0.12
        off_ms = 0.12
        pause = 1.2
        blink_span = 3 * (on_ms + off_ms)
        cycle = blink_span + pause
        pos = elapsed_s % cycle
        if pos < blink_span:
            step_b = on_ms + off_ms
            within = pos % step_b
            b = within < on_ms
    elif pattern == UploadLedPattern.FTP_ERROR:
        on_ms = 0.12
        off_ms = 0.12
        pause = 1.2
        blink_span = 3 * (on_ms + off_ms)
        cycle = blink_span + pause
        pos = elapsed_s % cycle
        if pos < blink_span:
            step_r = on_ms + off_ms
            within = pos % step_r
            r = within < on_ms
    elif pattern == UploadLedPattern.PARTIAL:
        # 3× yellow/red alternate (6 steps of 150ms)
        t = 0.15
        if elapsed_s < 6 * t:
            slot = int(elapsed_s / t)
            y = slot % 2 == 0
            r = slot % 2 == 1

    return {"green": g, "yellow": y, "red": r, "blue": b}


def pattern_finished(pattern: UploadLedPattern, elapsed_s: float) -> bool:
    """True when a one-shot pattern has completed (not looping patterns)."""
    if pattern == UploadLedPattern.SUCCESS:
        return elapsed_s >= 2.0 + 0.9
    if pattern == UploadLedPattern.EMPTY:
        unit = 4 * 0.12 + 0.4
        return elapsed_s >= 3 * unit
    if pattern == UploadLedPattern.PARTIAL:
        return elapsed_s >= 6 * 0.15
    return False
