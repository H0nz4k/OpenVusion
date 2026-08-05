"""HWSniff v2 headless orchestrator (GPIO + LEDs, shared ElaTool capture)."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from .collector_service import CollectorResult, create_collector
from .configuration import DEFAULT_CONFIG, deep_merge, load_config
from .dip import DipReader
from .gpio_backend import GpioBackend, create_backend
from .health import run_health_checks
from .leds import LED_NAMES, LedController, LedPins
from .logging_setup import setup_logging
from .network import NetworkMonitor
from .patterns import PatternKind, PatternTimings
from .reader_monitor import ReaderMonitor
from .service_restart import (
    SERVICE_RESTART_EXIT_CODE,
    consume_restart_marker,
    marker_path_from_config,
    write_restart_marker,
)
from .state import (
    CollectorOutcome,
    DeviceState,
    DipMode,
    RuntimeState,
    SweetBand,
    WlanStatus,
)
from .sweetp_bands import score_allows_read, thresholds_from_config
from .sweetp_filter import filter_config_from_sweet
from .sweetp_live import create_sweet_point
from .sweetp_stats import SweetPCycleStats
from .upload import UploadService, load_upload_settings

log = logging.getLogger(__name__)

# After SweetP/collector releases UART, skip presence probes briefly.
_UART_SETTLE_SECONDS = 0.75
_CHORD_WARN_BLINK_MS = 125
_CHORD_WARN_BLINKS = 4


class HeadlessApp:
    """Pi Zero 2 W GPIO appliance over the verified PCSniff/ElaTool engine."""

    def __init__(
        self,
        config: dict[str, Any] | Path | None = None,
        *,
        gpio: GpioBackend | None = None,
        collector=None,
        sweet_point=None,
        shutdown_callback: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        network: NetworkMonitor | None = None,
        reader_monitor: ReaderMonitor | None = None,
        upload_service: UploadService | None = None,
        loop_forever: bool = True,
        force_mock: bool = False,
    ) -> None:
        import time as _time

        if isinstance(config, Path):
            self.config = load_config(config)
        elif config is None:
            self.config = deep_merge(DEFAULT_CONFIG, {})
        else:
            self.config = deep_merge(DEFAULT_CONFIG, config)

        self._clock = clock or _time.monotonic
        self._sleep = sleep or _time.sleep
        self._loop_forever = loop_forever
        self._shutdown_callback = shutdown_callback or (lambda: None)
        self._stop_loop = False
        self._force_mock = force_mock or bool(self.config.get("gpio_prefer_mock"))

        gpio_cfg = self.config.get("gpio") or {}
        btn_cfg = gpio_cfg.get("buttons") or {}
        dip_cfg = gpio_cfg.get("dip") or {}
        led_cfg = gpio_cfg.get("leds") or {}
        pat_cfg = self.config.get("led_patterns") or {}
        net_cfg = self.config.get("network") or {}
        timing = self.config.get("timing") or {}

        prefer_mock = bool(self.config.get("gpio_prefer_mock"))
        if gpio is None:
            from .runtime import ensure_runtime_cwd

            ensure_runtime_cwd(self.config)
        self.gpio = gpio or create_backend(
            prefer_mock=prefer_mock, runtime_config=self.config
        )
        self.runtime = RuntimeState()
        sweet_cfg = self.config.get("sweetp") or {}
        self._thresholds = thresholds_from_config(sweet_cfg)
        self._filter_cfg = filter_config_from_sweet(sweet_cfg)

        timings = PatternTimings(
            slow_ms=int(pat_cfg.get("slow_ms", timing.get("error2_ms", 500))),
            fast_ms=int(
                pat_cfg.get("fast_ms", timing.get("read_progress_blink_ms", 250))
            ),
            single_flash_ms=int(pat_cfg.get("single_flash_ms", 150)),
            double_flash_ms=int(pat_cfg.get("double_flash_ms", 150)),
            triple_flash_ms=int(pat_cfg.get("triple_flash_ms", 100)),
            border_ms=int(
                pat_cfg.get("border_ms", timing.get("sweetp_border_ms", 250))
            ),
            heartbeat_period_ms=int(
                pat_cfg.get(
                    "heartbeat_period_ms",
                    float(timing.get("wlan_period_seconds", 3)) * 1000,
                )
            ),
            heartbeat_pulse_ms=int(
                pat_cfg.get("heartbeat_pulse_ms", timing.get("wlan_pulse_ms", 120))
            ),
            error3_on_ms=int(pat_cfg.get("error3_on_ms", timing.get("error3_ms", 500))),
            error3_off_ms=int(pat_cfg.get("error3_off_ms", timing.get("error3_ms", 500))),
            error3_pause_ms=int(
                pat_cfg.get("error3_pause_ms", timing.get("error3_pause_ms", 1500))
            ),
            count_blink_ms=int(
                pat_cfg.get("count_blink_ms", timing.get("read_complete_ms", 500))
            ),
            count_blink_count=int(
                pat_cfg.get(
                    "count_blink_count", timing.get("read_complete_count", 5)
                )
            ),
        )
        self.leds = LedController(
            self.gpio,
            LedPins(
                green=int(led_cfg.get("green", 19)),
                yellow=int(led_cfg.get("yellow", 16)),
                red=int(led_cfg.get("red", 26)),
                blue=int(led_cfg.get("blue", 20)),
                active_high=bool(led_cfg.get("active_high", True)),
            ),
        )
        self.leds.engine.timings = timings
        self.leds.engine._clock = self._clock

        self.buttons = ButtonWatcher(
            self.gpio,
            ButtonConfig(
                start_pin=int(btn_cfg.get("start", 21)),
                stop_pin=int(btn_cfg.get("stop", 6)),
                active_low=bool(btn_cfg.get("active_low", True)),
                pull_up=bool(btn_cfg.get("pull_up", True)),
                debounce_ms=int(btn_cfg.get("debounce_ms", 50)),
                shutdown_hold_seconds=float(
                    btn_cfg.get("shutdown_hold_seconds", 3)
                ),
                chord_hold_seconds=float(btn_cfg.get("chord_hold_seconds", 5)),
                chord_warn_seconds=float(btn_cfg.get("chord_warn_seconds", 4)),
            ),
            clock=self._clock,
        )
        self.dip = DipReader(
            self.gpio,
            dip1_pin=int(dip_cfg.get("dip1", 12)),
            dip2_pin=int(dip_cfg.get("dip2", 13)),
            active_low=bool(dip_cfg.get("active_low", True)),
            pull_up=bool(dip_cfg.get("pull_up", True)),
        )
        self.network = network or NetworkMonitor(
            interface=str(net_cfg.get("interface", "wlan0")),
            poll_seconds=float(net_cfg.get("poll_seconds", 3)),
            clock=self._clock,
        )
        self.reader_monitor = reader_monitor or ReaderMonitor(
            self.config, clock=self._clock
        )

        self.collector = collector or create_collector(
            self.config, clock=self._clock, force_mock=self._force_mock
        )
        self.collector.on_phase_started = self._on_phase_started
        self.collector.on_reader_complete = self._on_reader_complete
        self.collector.on_save_started = self._on_save_started
        if hasattr(self.collector, "on_error"):
            self.collector.on_error = self._on_collector_error

        self.sweet_point = sweet_point or create_sweet_point(
            self.config,
            clock=self._clock,
            sleep=self._sleep,
            force_mock=self._force_mock,
        )
        self.upload = upload_service or UploadService(
            load_upload_settings(self.config),
            clock=self._clock,
            sleep=self._sleep,
        )

        self._gpio_ok = True
        self._cancel_phase: str | None = None
        self._awaiting_save = False
        self._read_complete_done = False
        self._reader_lost_during_capture = False
        self._uart_owner: str | None = None  # "sweetp" | "collector"
        self._uart_release_at: float | None = None
        self._sweetp_stats = SweetPCycleStats(
            max_trace_samples=self._filter_cfg.max_trace_samples
        )
        self._sweetp_snapshot = None
        self._sweet_trend_active = False
        self._chord_warning_active = False
        self._chord_led_backup: dict[str, PatternKind] | None = None
        self._restart_exit_code: int | None = None
        self._restart_marker = marker_path_from_config(self.config)

    # ------------------------------------------------------------------ lifecycle

    def run(self) -> int:
        log_root = Path(self.config.get("log_root", "/var/log/hwsniff"))
        try:
            setup_logging(log_root)
        except Exception:  # noqa: BLE001
            logging.basicConfig(level=logging.INFO)
        log.info(
            "HWSniff v2 boot version=%s profile=%s",
            __version__,
            self.config.get("hardware_profile"),
        )
        try:
            self.boot()
        except Exception as exc:  # noqa: BLE001
            self._enter_error1(exc, state="BOOT", reader_op="boot")
        while not self._stop_loop:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                self._enter_error1(
                    exc,
                    state=self.runtime.device_state.value,
                    reader_op="tick",
                )
            if not self._loop_forever:
                break
            self._sleep(0.02)
        self.close()
        if self._restart_exit_code is not None:
            return int(self._restart_exit_code)
        return 0 if self.runtime.device_state not in (
            DeviceState.ERROR1,
        ) else 1

    def close(self) -> None:
        try:
            self._leave_upload()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sweet_point.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.collector.is_running():
                self.collector.request_stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.leds.all_off()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.gpio.close()
        except Exception:  # noqa: BLE001
            pass

    def request_exit(self) -> None:
        self._stop_loop = True

    def boot(self) -> None:
        self._enter(DeviceState.BOOT)
        self.leds.all_off()

        d1, d2 = self.dip.read_raw()
        self.runtime.dip1_on = d1
        self.runtime.dip2_on = d2
        self.runtime.dip_mode = self.dip.read_mode()
        log.info(
            "DIP at boot: dip1=%s dip2=%s mode=%s",
            "ON" if d1 else "OFF",
            "ON" if d2 else "OFF",
            self.runtime.dip_mode.value,
        )

        self_test = self.config.get("self_test") or {}
        if bool(self_test.get("enabled", True)):
            cycles = int(self_test.get("cycles", 2))
            led_ms = int(self_test.get("led_ms", 500))
            self._led_self_test(led_ms, cycles)

        # Filesystem
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
            require_wlan=False,
        )
        if not report.ok:
            self._enter_error1(
                RuntimeError(";".join(report.errors)),
                state="BOOT",
                reader_op="filesystem",
            )
            return

        self.network.tick(self._clock())
        self.runtime.wlan = self.network.status
        self.runtime.wlan_ip = self.network.ip

        # Boot rules: ERROR3 (both ON) / SWEETP-at-boot invalid on cold start;
        # chord service-restart may leave a one-shot marker to resume DIP mode.
        restart_resume = consume_restart_marker(self._restart_marker)
        if self.runtime.dip_mode == DipMode.ERROR3:
            self._enter(DeviceState.ERROR3)
            _ = self.buttons.poll()
            return
        if self.runtime.dip_mode == DipMode.SWEETP and not restart_resume:
            log.error("Boot DIP1 ON — ERROR3 (start in MAIN or UPLOAD)")
            self._enter(DeviceState.ERROR3)
            _ = self.buttons.poll()
            return
        if self.runtime.dip_mode == DipMode.UPLOAD:
            _ = self.buttons.poll()
            self._enter_upload()
            return

        presence = self.reader_monitor.tick(force=True)
        if presence.present:
            self.runtime.reader_port = presence.port
            self.runtime.reader_version = presence.version
        _ = self.buttons.poll()

        if not presence.present:
            self._enter(DeviceState.ERROR2)
            return

        if self.runtime.dip_mode == DipMode.SWEETP and restart_resume:
            log.info("Service restart resume — entering SWEETP from marker")
            self._enter_sweetp()
            return

        self._enter(DeviceState.READY)

    def tick(self) -> None:
        now = self._clock()
        if self.network.tick(now):
            self.runtime.wlan = self.network.status
            self.runtime.wlan_ip = self.network.ip
            if not self._chord_warning_active:
                self._apply_wlan_led()

        # Chord has global priority — poll buttons before DIP/work handlers.
        button_events = self.buttons.poll()
        chord = self.buttons.chord_status()
        if chord.cancelled:
            self._cancel_chord_warning()
        self._update_chord_warning(chord)
        if ButtonEvent.RESTART_CHORD in button_events:
            self._trigger_service_restart()
            self.leds.tick(now)
            return

        self._poll_dip()

        st = self.runtime.device_state
        if st == DeviceState.ERROR2:
            self._tick_error2(now)
        elif st == DeviceState.ERROR3:
            pass  # wait for DIP recovery
        elif st == DeviceState.UPLOAD:
            pass  # reader not required during FTP upload
        elif self._poll_reader_hotplug(now):
            # READ stays active until collector drains; other states already ERROR2.
            if self.runtime.device_state != DeviceState.READ:
                self.leds.tick(now)
                return

        for ev in button_events:
            if ev == ButtonEvent.RESTART_CHORD:
                continue
            self._handle_button(ev)

        if self.runtime.device_state == DeviceState.UPLOAD:
            if not self._chord_warning_active:
                self._tick_upload_leds()
            self.leds.tick(now)
            return

        if self.runtime.device_state in (
            DeviceState.SWEETP,
            DeviceState.POSITIONING,
        ):
            self._tick_sweet(now)
            # LiveSweetPoint may surface serial loss before USB unplug is seen.
            if self._sweet_reader_failed():
                self._on_reader_lost(self.runtime.device_state)
                self.leds.tick(now)
                return
        elif self.runtime.device_state in (
            DeviceState.READ,
            DeviceState.READ_COMPLETE,
            DeviceState.SAVE,
        ):
            self.collector.tick(now)
            self._poll_collector()

        self.leds.tick(now)

    # ------------------------------------------------------------------ DIP

    def _poll_dip(self) -> None:
        d1, d2 = self.dip.read_raw()
        mode = self.dip.read_mode()
        changed = (
            d1 != self.runtime.dip1_on
            or d2 != self.runtime.dip2_on
            or mode != self.runtime.dip_mode
        )
        if not changed:
            return
        prev = self.runtime.dip_mode
        self.runtime.dip1_on = d1
        self.runtime.dip2_on = d2
        self.runtime.dip_mode = mode
        log.info(
            "DIP change %s → %s (dip1=%s dip2=%s)",
            prev.value,
            mode.value,
            "ON" if d1 else "OFF",
            "ON" if d2 else "OFF",
        )

        if mode == DipMode.ERROR3:
            self._leave_upload()
            self._abort_active_work()
            self._enter(DeviceState.ERROR3)
            return

        if self.runtime.device_state == DeviceState.ERROR3:
            # Recovery without restart
            self._recover_from_error3(mode)
            return

        if mode == DipMode.UPLOAD:
            if self.runtime.device_state != DeviceState.UPLOAD:
                self._abort_active_work()
                self._enter_upload()
            return

        # Leaving upload toward MAIN / SWEETP
        if self.runtime.device_state == DeviceState.UPLOAD:
            self._leave_upload()

        if mode == DipMode.SWEETP:
            if self.runtime.device_state != DeviceState.SWEETP:
                self._abort_active_work()
                self._enter_sweetp()
            return

        # MAIN
        if self.runtime.device_state == DeviceState.SWEETP:
            self._leave_sweetp()
        elif self.runtime.device_state != DeviceState.READY:
            # Return from upload / cancelled work to READY when possible
            if self._uart_busy():
                if self.runtime.reader_port:
                    self._enter(DeviceState.READY)
                else:
                    self._enter(DeviceState.ERROR2)
                return
            presence = self.reader_monitor.tick(force=True)
            if presence.present and presence.port:
                self.runtime.reader_port = presence.port
                self._enter(DeviceState.READY)
            elif self.runtime.reader_port:
                self._enter(DeviceState.READY)
            else:
                self._enter(DeviceState.ERROR2)

    def _recover_from_error3(self, mode: DipMode) -> None:
        log.info("ERROR3 cleared — health check + resume mode=%s", mode.value)
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
        )
        if not report.ok:
            self._enter_error1(
                RuntimeError(";".join(report.errors)),
                state="ERROR3_RECOVERY",
                reader_op="health",
            )
            return
        if mode == DipMode.UPLOAD:
            self._enter_upload()
            return
        presence = self.reader_monitor.tick(force=True)
        if presence.present and presence.port:
            self.runtime.reader_port = presence.port
        if not presence.present:
            self._enter(DeviceState.ERROR2)
            return
        if mode == DipMode.SWEETP:
            self._enter_sweetp()
        else:
            self._enter(DeviceState.READY)

    def _enter_upload(self) -> None:
        log.info("Enter UPLOAD mode")
        self._abort_active_work()
        self._release_uart()
        self._enter(DeviceState.UPLOAD)
        self.upload.start()

    def _leave_upload(self) -> None:
        if self.upload.running or self.runtime.device_state == DeviceState.UPLOAD:
            log.info("Leave UPLOAD mode")
            self.upload.stop()

    def _tick_upload_leds(self) -> None:
        levels = self.upload.led_levels()
        # Drive LEDs directly so chase patterns stay mutually exclusive
        for name in LED_NAMES:
            on = bool(levels.get(name))
            self.leds.set_pattern(
                name, PatternKind.ON if on else PatternKind.OFF
            )
        self.leds.tick()

    def _abort_active_work(self) -> None:
        self._awaiting_save = False
        self._read_complete_done = False
        try:
            self.sweet_point.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._uart_owner == "sweetp":
            self._release_uart()
        if self.collector.is_running():
            self.collector.request_stop()
            for _ in range(50):
                self.collector.tick(self._clock())
                if not self.collector.is_running():
                    break
                self._sleep(0.02)
            _ = self.collector.get_result()
        if self._uart_owner == "collector":
            self._release_uart()
        self.runtime.active_cycle_mode = None
        self.runtime.collector_running = False
        self.runtime.read_step = 0
        self._reset_sweetp_cycle()

    # ------------------------------------------------------------------ UART ownership

    def _uart_busy(self) -> bool:
        if self._uart_owner is not None:
            return True
        if self._uart_release_at is None:
            return False
        return (self._clock() - self._uart_release_at) < _UART_SETTLE_SECONDS

    def _claim_uart(self, owner: str) -> None:
        self._uart_owner = owner
        self._uart_release_at = None

    def _release_uart(self) -> None:
        self._uart_owner = None
        self._uart_release_at = self._clock()

    def _remember_port(self, port: str | None, version: str | None = None) -> None:
        if port:
            self.runtime.reader_port = port
            if version:
                self.runtime.reader_version = version

    # ------------------------------------------------------------------ SweetP

    def _enter_sweetp(self) -> bool:
        """Enter SWEETP only with a valid port. Otherwise stay/go ERROR2."""
        if self._uart_owner == "collector":
            log.warning("SweetP deferred — collector owns UART")
            self._enter(DeviceState.ERROR2)
            return False
        port = self.runtime.reader_port
        if not port and not self._uart_busy():
            presence = self.reader_monitor.tick(force=True)
            if presence.present and presence.port:
                self._remember_port(presence.port, presence.version)
                port = presence.port
        if not port:
            log.warning("SweetP refused — no reader port (DIP=%s)", self.runtime.dip_mode.value)
            self._enter(DeviceState.ERROR2)
            return False
        if self._uart_owner == "sweetp":
            try:
                self.sweet_point.stop()
            except Exception:  # noqa: BLE001
                pass
            self._release_uart()
        self._claim_uart("sweetp")
        started = self.sweet_point.start(port)
        if not started:
            self._release_uart()
            self._enter(DeviceState.ERROR2)
            return False
        self._enter(DeviceState.SWEETP)
        return True

    def _leave_sweetp(self) -> None:
        """Stop SweetP without treating UART release as reader unplug."""
        try:
            self.sweet_point.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._uart_owner == "sweetp":
            self._release_uart()
        self.runtime.sweet_band = SweetBand.NONE
        self.runtime.sweet_score = None
        self.runtime.sweet_has_tag = False
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
        )
        if not report.ok:
            self._enter_error1(
                RuntimeError(";".join(report.errors)),
                state="LEAVE_SWEETP",
                reader_op="health",
            )
            return
        # Keep last known port; READY hotplug reconfirms after settle.
        if self.runtime.reader_port:
            self._enter(DeviceState.READY)
            return
        if self._uart_busy():
            self._enter(DeviceState.ERROR2)
            return
        presence = self.reader_monitor.tick(force=True)
        if presence.present and presence.port:
            self._remember_port(presence.port, presence.version)
            self._enter(DeviceState.READY)
        else:
            self._enter(DeviceState.ERROR2)

    def _tick_sweet(self, now: float) -> None:
        sample = self.sweet_point.tick(now)
        prev_band = self.runtime.sweet_band
        # stable score drives band + READ; fast is overlay-only
        self.runtime.sweet_score = sample.score
        self.runtime.sweet_band = sample.band
        self.runtime.sweet_has_tag = sample.has_tag
        if self.runtime.device_state == DeviceState.POSITIONING:
            self.runtime.positioning_score = sample.score
            self._sweetp_stats.add_sample(
                sample.score,
                has_tag=sample.has_tag,
                trace_row={
                    "seq": sample.seq,
                    "t_ms": sample.t_ms,
                    "raw_score": sample.raw_score,
                    "fast_score": sample.fast_score,
                    "stable_score": sample.score,
                    "trend": sample.trend_pps,
                    "band": sample.band.value,
                    "tag_present": sample.has_tag,
                    "reader_latency_ms": sample.reader_latency_ms,
                    "accepted": False,
                },
            )
        if sample.band != prev_band:
            log.info(
                "SweetP band %s → %s stable=%.1f fast=%s",
                prev_band.value,
                sample.band.value,
                sample.score if sample.score is not None else -1.0,
                f"{sample.fast_score:.1f}" if sample.fast_score is not None else "n/a",
            )
        if not self._chord_warning_active:
            self._apply_sweet_leds(
                sample.band,
                trend_direction=sample.trend_direction,
                blink_interval_ms=sample.blink_interval_ms,
            )

    def _sweet_reader_failed(self) -> bool:
        err = getattr(self.sweet_point, "reader_error", None)
        return bool(err)

    def _clear_sweet_trend(self) -> None:
        self._sweet_trend_active = False

    def _poll_reader_hotplug(self, now: float) -> bool:
        """Monitor TWN4 presence. Return True if transitioned to ERROR2.

        Only while READY and UART is free. During SWEETP / POSITIONING / READ
        the appliance owns the UART exclusively.
        """
        st = self.runtime.device_state
        if st != DeviceState.READY:
            return False
        if self._uart_busy():
            return False
        presence = self.reader_monitor.tick(now)
        if presence.present:
            self._remember_port(presence.port, presence.version)
            return False
        # Do not wipe known port on a single failed probe after UART release.
        self._on_reader_lost(st)
        return True

    def _on_reader_lost(self, st: DeviceState) -> None:
        log.warning("Reader lost in %s → ERROR2", st.value)
        if st in (DeviceState.SWEETP, DeviceState.POSITIONING):
            try:
                self.sweet_point.stop()
            except Exception:  # noqa: BLE001
                pass
            if self._uart_owner == "sweetp":
                self._release_uart()
            self.runtime.active_cycle_mode = None
            self.runtime.sweet_band = SweetBand.NONE
            self.runtime.sweet_score = None
            self.runtime.sweet_has_tag = False
            self._reset_sweetp_cycle()
            self._enter(DeviceState.ERROR2)
            return
        if st == DeviceState.READY:
            self._enter(DeviceState.ERROR2)
            return
        if st == DeviceState.READ:
            self._reader_lost_during_capture = True
            if self.collector.is_running():
                self.collector.request_stop()
            else:
                self.runtime.active_cycle_mode = None
                if self._uart_owner == "collector":
                    self._release_uart()
                self._enter(DeviceState.ERROR2)
            return

    def _apply_sweet_leds(
        self,
        band: SweetBand,
        *,
        trend_direction: str = "stable",
        blink_interval_ms: int | None = None,
    ) -> None:
        """Base band from stable_score + optional trend overlay from fast_score."""
        pulse = int(self._filter_cfg.trend_pulse_ms)
        improving = trend_direction == "improving" and blink_interval_ms is not None
        worsening = trend_direction == "worsening" and blink_interval_ms is not None
        # Collision: same-color overlay is invisible — keep solid base.
        if band == SweetBand.GOOD and improving:
            improving = False
        if band == SweetBand.BAD and worsening:
            worsening = False

        if band == SweetBand.GOOD:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            if worsening:
                self.leds.set_pattern(
                    "red",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self._sweet_trend_active = True
            else:
                self.leds.set_pattern("red", PatternKind.OFF)
                self._sweet_trend_active = False
        elif band == SweetBand.USABLE:
            self.leds.set_pattern("yellow", PatternKind.ON)
            if improving:
                self.leds.set_pattern(
                    "green",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self.leds.set_pattern("red", PatternKind.OFF)
                self._sweet_trend_active = True
            elif worsening:
                self.leds.set_pattern("green", PatternKind.OFF)
                self.leds.set_pattern(
                    "red",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self._sweet_trend_active = True
            else:
                self.leds.set_pattern("green", PatternKind.OFF)
                self.leds.set_pattern("red", PatternKind.OFF)
                self._sweet_trend_active = False
        elif band == SweetBand.BORDERLINE:
            # Keep alternating Y/R base; overlay uses the free channel when possible.
            if improving:
                self.leds.set_pattern("yellow", PatternKind.ON)
                self.leds.set_pattern(
                    "green",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self.leds.set_pattern("red", PatternKind.OFF)
                self._sweet_trend_active = True
            elif worsening:
                self.leds.set_pattern("yellow", PatternKind.ON)
                self.leds.set_pattern("green", PatternKind.OFF)
                self.leds.set_pattern(
                    "red",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self._sweet_trend_active = True
            else:
                self.leds.set_pattern("green", PatternKind.OFF)
                self.leds.set_pattern("yellow", PatternKind.PHASE_A)
                self.leds.set_pattern("red", PatternKind.PHASE_B)
                self._sweet_trend_active = False
        elif band == SweetBand.BAD:
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.ON)
            if improving:
                self.leds.set_pattern(
                    "green",
                    PatternKind.PERIODIC_PULSE,
                    period_ms=int(blink_interval_ms),
                    pulse_ms=pulse,
                )
                self._sweet_trend_active = True
            else:
                self.leds.set_pattern("green", PatternKind.OFF)
                self._sweet_trend_active = False
        else:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
            self._sweet_trend_active = False
        self._apply_wlan_led()

    # ------------------------------------------------------------------ buttons

    def _handle_button(self, ev: ButtonEvent) -> None:
        st = self.runtime.device_state
        log.info("Button %s in %s", ev.value, st.value)

        if st in (
            DeviceState.ERROR1,
            DeviceState.ERROR2,
            DeviceState.ERROR3,
            DeviceState.BOOT,
            DeviceState.UPLOAD,
        ):
            return

        if st == DeviceState.SWEETP:
            # START ignored — DIP-controlled
            return

        if ev == ButtonEvent.STOP_SHORT:
            if st in (
                DeviceState.POSITIONING,
                DeviceState.READ,
                DeviceState.READ_COMPLETE,
                DeviceState.SAVE,
            ):
                self._request_cancel()
            return

        if ev == ButtonEvent.STOP_LONG:
            # Reserved; not mandatory poweroff in v2
            if st in (
                DeviceState.POSITIONING,
                DeviceState.READ,
                DeviceState.READ_COMPLETE,
                DeviceState.SAVE,
            ):
                self._request_cancel()
            return

        if ev == ButtonEvent.START_SHORT:
            if st == DeviceState.READY:
                self._begin_positioning()
            elif st == DeviceState.POSITIONING:
                self._try_begin_read()
            return

    def _begin_positioning(self) -> None:
        if self.runtime.dip_mode != DipMode.MAIN:
            log.info("START ignored — not MAIN (mode=%s)", self.runtime.dip_mode.value)
            return
        if self.runtime.device_state == DeviceState.UPLOAD or self.upload.running:
            log.info("START ignored — upload mode active")
            return
        self.runtime.active_cycle_mode = DipMode.MAIN
        port = self.runtime.reader_port
        if not port and not self._uart_busy():
            presence = self.reader_monitor.tick(force=True)
            if presence.present and presence.port:
                self._remember_port(presence.port, presence.version)
                port = presence.port
        if not port:
            self._enter(DeviceState.ERROR2)
            return
        self._reset_sweetp_cycle()
        self._claim_uart("sweetp")
        if not self.sweet_point.start(port):
            self._release_uart()
            self._enter(DeviceState.ERROR2)
            return
        log.info("SweetP positioning cycle started")
        self._enter(DeviceState.POSITIONING)

    def _reset_sweetp_cycle(self) -> None:
        cfg = dict(self._filter_cfg.to_dict())
        live_cfg = getattr(self.sweet_point, "filter_config_dict", None)
        if callable(live_cfg):
            cfg = live_cfg()
        elif isinstance(live_cfg, dict):
            cfg = live_cfg
        self._sweetp_stats.reset(filter_config=cfg)
        self._sweetp_snapshot = None
        self._clear_sweet_trend()

    def _try_begin_read(self) -> None:
        # READ acceptance uses stable score only (never fast_score).
        score = self.runtime.sweet_score
        has_tag = self.runtime.sweet_has_tag
        if not score_allows_read(
            score, has_tag=has_tag, thresholds=self._thresholds
        ):
            log.info(
                "start_rejected_due_to_quality stable_score=%s has_tag=%s",
                score,
                has_tag,
            )
            return
        self.runtime.positioning_score = score
        band = self.runtime.sweet_band.value if self.runtime.sweet_band else None
        snapshot = self._sweetp_stats.freeze(
            score_at_accept=score, band_at_accept=band
        )
        self._sweetp_snapshot = snapshot
        log.info(
            "READ accepted stable_score=%s band=%s samples=%s "
            "min=%s avg=%s max=%s",
            snapshot.score_at_accept,
            snapshot.band_at_accept,
            snapshot.sample_count,
            snapshot.minimum,
            snapshot.average,
            snapshot.maximum,
        )
        # Release SweetP before opening capture serial
        self._clear_sweet_trend()
        self.sweet_point.stop()
        if self._uart_owner == "sweetp":
            self._release_uart()
        self.runtime.read_step = 0
        self._awaiting_save = False
        self._read_complete_done = False
        self._reader_lost_during_capture = False
        if not self.runtime.reader_port:
            self._enter(DeviceState.ERROR2)
            return
        self._claim_uart("collector")
        self._enter(DeviceState.READ)
        self.runtime.collector_running = True
        artifacts: dict[str, str] = {}
        trace = snapshot.trace_jsonl()
        if trace:
            artifacts["sweetp_trace.jsonl"] = trace
        self.collector.start(
            DipMode.MAIN,
            port=self.runtime.reader_port,
            summary_extra={"sweetp": snapshot.to_dict()},
            artifact_files=artifacts,
        )

    def _request_cancel(self) -> None:
        log.info("STOP → request_stop / cancel")
        st = self.runtime.device_state
        if st == DeviceState.POSITIONING:
            self.sweet_point.stop()
            if self._uart_owner == "sweetp":
                self._release_uart()
            self._reset_sweetp_cycle()
            self._begin_cancel_sequence()
            return
        if self.collector.is_running():
            self.collector.request_stop()
            # Result handled in _poll_collector → CANCELLED
            return
        self._begin_cancel_sequence()

    # ------------------------------------------------------------------ collector

    def _on_phase_started(self, phase: str) -> None:
        from .state import READ_PHASE_STEPS

        step = READ_PHASE_STEPS.get(phase, self.runtime.read_step)
        self.runtime.read_step = step
        self.runtime.collector_progress = phase
        log.info("READ phase started: %s (step %s/6)", phase, step)
        if self.runtime.device_state == DeviceState.READ:
            self._apply_read_progress(step)

    def _on_reader_complete(self) -> None:
        if self.runtime.device_state not in (
            DeviceState.READ,
            DeviceState.READ_COMPLETE,
        ):
            return
        if self._read_complete_done:
            return
        self._read_complete_done = True
        log.info("Reader complete — G+Y+R blink 5× (tag may be removed)")
        self._enter(DeviceState.READ_COMPLETE)
        count = self.leds.engine.timings.count_blink_count

        def _after_blink() -> None:
            if self.runtime.device_state != DeviceState.READ_COMPLETE:
                return
            self._awaiting_save = True
            # SAVE LED applied when collector reports saving / result path
            if not self.collector.is_running():
                # Mock may finish save after blink; ensure SAVE state
                self._enter(DeviceState.SAVE)

        self.leds.set_pattern("green", PatternKind.COUNT_BLINK, count=count)
        self.leds.set_pattern("yellow", PatternKind.COUNT_BLINK, count=count)
        self.leds.set_pattern(
            "red",
            PatternKind.COUNT_BLINK,
            count=count,
            on_complete=_after_blink,
        )
        self._apply_wlan_led()

    def _on_save_started(self) -> None:
        log.info("SAVE started")
        if self.runtime.device_state in (
            DeviceState.READ,
            DeviceState.READ_COMPLETE,
            DeviceState.SAVE,
        ):
            self._enter(DeviceState.SAVE)

    def _on_collector_error(self, err: dict[str, Any]) -> None:
        log.error(
            "Collector error type=%s msg=%s",
            err.get("exception_type"),
            err.get("message"),
        )

    def _poll_collector(self) -> None:
        if self.runtime.device_state not in (
            DeviceState.READ,
            DeviceState.READ_COMPLETE,
            DeviceState.SAVE,
        ):
            return
        if self.collector.is_running():
            return
        result = self.collector.get_result()
        if result is None:
            return
        self._handle_collector_result(result)

    def _handle_collector_result(self, result: CollectorResult) -> None:
        self.runtime.last_outcome = result.outcome
        self.runtime.collector_running = False
        self.runtime.locked_uid = result.uid
        if self._uart_owner == "collector":
            self._release_uart()
        log.info(
            "Collector result: %s uid=%s dir=%s",
            result.outcome.value,
            result.uid,
            result.directory,
        )

        # Disconnect during READ: keep persisted data, then ERROR2 (not cancel UI).
        if self._reader_lost_during_capture:
            self._persist_then_error2(result)
            return

        if result.outcome == CollectorOutcome.FAILED and not result.fatal_save:
            if not self._uart_busy():
                presence = self.reader_monitor.tick(force=True)
                if not presence.present:
                    self._persist_then_error2(result)
                    return

        if result.outcome == CollectorOutcome.CANCELLED:
            self._begin_cancel_sequence()
            return

        if result.fatal_save or (
            result.outcome == CollectorOutcome.FAILED
            and "persistence" in (result.message or "").lower()
        ):
            self._enter_error1(
                RuntimeError(result.message or "save_failed"),
                state="SAVE",
                reader_op="save",
                uid=result.uid,
                output_dir=result.directory,
            )
            return

        if result.outcome == CollectorOutcome.FAILED:
            # No usable dataset
            self._enter_error1(
                RuntimeError(result.message or "capture_failed"),
                state="READ",
                reader_op="capture",
                uid=result.uid,
                output_dir=result.directory,
            )
            return

        # SUCCESS or PARTIAL → READY / SWEETP (keep known port across UART settle)
        self.runtime.active_cycle_mode = None
        self._sweetp_snapshot = None
        if not self._uart_busy():
            presence = self.reader_monitor.tick(force=True)
            if presence.present and presence.port:
                self._remember_port(presence.port, presence.version)
        if not self.runtime.reader_port:
            self._enter(DeviceState.ERROR2)
            return
        if self.runtime.dip_mode == DipMode.SWEETP:
            self._enter_sweetp()
        else:
            self._enter(DeviceState.READY)

    def _persist_then_error2(self, result: CollectorResult) -> None:
        log.warning(
            "Reader lost during capture outcome=%s — ERROR2", result.outcome.value
        )
        self._reader_lost_during_capture = False
        self.runtime.active_cycle_mode = None
        self.runtime.collector_running = False
        if self._uart_owner == "collector":
            self._release_uart()
        self._enter(DeviceState.ERROR2)

    # ------------------------------------------------------------------ ERROR2

    def _tick_error2(self, now: float) -> None:
        if self._uart_busy():
            return
        presence = self.reader_monitor.tick(now)
        if not presence.present:
            return
        log.info(
            "Reader hotplug → health check → resume (DIP=%s)",
            self.runtime.dip_mode.value,
        )
        self._remember_port(presence.port, presence.version)
        self._reader_lost_during_capture = False
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
        )
        if not report.ok:
            self._enter_error1(
                RuntimeError(";".join(report.errors)),
                state="ERROR2_RECOVERY",
                reader_op="health",
            )
            return
        if self.runtime.dip_mode == DipMode.ERROR3:
            self._enter(DeviceState.ERROR3)
            return
        if self.runtime.dip_mode == DipMode.UPLOAD:
            self._enter_upload()
            return
        if self.runtime.dip_mode == DipMode.SWEETP:
            self._enter_sweetp()
        else:
            self._enter(DeviceState.READY)

    # ------------------------------------------------------------------ cancel / errors

    def _begin_cancel_sequence(self) -> None:
        self._cancel_phase = "red"
        self.runtime.active_cycle_mode = None
        self.runtime.collector_running = False
        self._enter(DeviceState.CANCELLED)

    def _enter_error1(
        self,
        exc: BaseException,
        *,
        state: str,
        reader_op: str,
        uid: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log.error(
            "ERROR1 type=%s message=%s state=%s reader_op=%s uid=%s output=%s\n%s",
            type(exc).__name__,
            exc,
            state,
            reader_op,
            uid or self.runtime.locked_uid,
            output_dir,
            tb,
        )
        self.runtime.last_error = f"{type(exc).__name__}: {exc}"
        self._enter(DeviceState.ERROR1, error=self.runtime.last_error)

    def _enter(self, state: DeviceState, *, error: str | None = None) -> None:
        prev = self.runtime.device_state
        self.runtime.device_state = state
        if error:
            self.runtime.last_error = error
        log.info("State %s → %s", prev.value, state.value)
        if state not in (DeviceState.SWEETP, DeviceState.POSITIONING):
            self._clear_sweet_trend()
        self._apply_state_leds(state)
        if state == DeviceState.CANCELLED:
            self._start_cancel_red_flash()

    def _start_cancel_red_flash(self) -> None:
        self.leds.set_pattern("green", PatternKind.OFF)
        self.leds.set_pattern("yellow", PatternKind.OFF)
        self.leds.set_pattern(
            "red",
            PatternKind.SINGLE,
            on_complete=self._cancel_to_ready,
        )
        self._apply_wlan_led()

    def _cancel_to_ready(self) -> None:
        if self.runtime.device_state != DeviceState.CANCELLED:
            return
        self._cancel_phase = None
        if self.runtime.dip_mode == DipMode.ERROR3:
            self._enter(DeviceState.ERROR3)
        elif self.runtime.dip_mode == DipMode.SWEETP:
            self._enter_sweetp()
        elif self.runtime.reader_port:
            self._enter(DeviceState.READY)
        elif self._uart_busy():
            self._enter(DeviceState.ERROR2)
        else:
            presence = self.reader_monitor.tick(force=True)
            if presence.present and presence.port:
                self._remember_port(presence.port, presence.version)
                self._enter(DeviceState.READY)
            else:
                self._enter(DeviceState.ERROR2)

    # ------------------------------------------------------------------ service restart chord

    def _update_chord_warning(self, chord) -> None:
        if chord.warning and not self._chord_warning_active:
            self._chord_warning_active = True
            self._chord_led_backup = {
                name: self.leds.engine.get_kind(name) for name in LED_NAMES
            }
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern(
                "red",
                PatternKind.COUNT_BLINK,
                count=_CHORD_WARN_BLINKS,
                step_ms=_CHORD_WARN_BLINK_MS,
            )
            self.leds.set_pattern("blue", PatternKind.OFF)
        elif not chord.both_held and not chord.warning and self._chord_warning_active:
            if not chord.fired:
                self._cancel_chord_warning()

    def _cancel_chord_warning(self) -> None:
        if not self._chord_warning_active:
            return
        self._chord_warning_active = False
        backup = self._chord_led_backup
        self._chord_led_backup = None
        if backup:
            for name, kind in backup.items():
                self.leds.set_pattern(name, kind)
        else:
            self._apply_state_leds(self.runtime.device_state)

    def _trigger_service_restart(self) -> None:
        log.info("Service restart chord triggered")
        self._chord_warning_active = False
        self._chord_led_backup = None
        write_restart_marker(self._restart_marker)
        try:
            self._leave_upload()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sweet_point.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.collector.is_running():
            try:
                self.collector.request_stop()
                for _ in range(50):
                    self.collector.tick(self._clock())
                    if not self.collector.is_running():
                        break
                    self._sleep(0.02)
                _ = self.collector.get_result()
            except Exception:  # noqa: BLE001
                pass
        self._uart_owner = None
        self._uart_release_at = None
        try:
            self.leds.all_off()
        except Exception:  # noqa: BLE001
            pass
        for handler in logging.root.handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001
                pass
        self._restart_exit_code = SERVICE_RESTART_EXIT_CODE
        self._stop_loop = True

    # ------------------------------------------------------------------ LEDs

    def _apply_read_progress(self, step: int) -> None:
        """6-step progress bar: blink = first half of segment, solid = complete."""
        # step 1: G blink; 2: G solid; 3: G solid+Y blink; 4: G+Y solid;
        # 5: G+Y solid+R blink; 6: G+Y+R solid
        g = PatternKind.OFF
        y = PatternKind.OFF
        r = PatternKind.OFF
        if step >= 1:
            g = PatternKind.FAST if step == 1 else PatternKind.ON
        if step >= 3:
            y = PatternKind.FAST if step == 3 else PatternKind.ON
        if step >= 5:
            r = PatternKind.FAST if step == 5 else PatternKind.ON
        self.leds.set_pattern("green", g)
        self.leds.set_pattern("yellow", y)
        self.leds.set_pattern("red", r)
        self._apply_wlan_led()

    def _apply_state_leds(self, state: DeviceState) -> None:
        if self._chord_warning_active:
            return
        if state == DeviceState.BOOT:
            self.leds.all_off()
        elif state == DeviceState.READY:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.POSITIONING:
            # Sweet LEDs applied by _tick_sweet
            pass
        elif state == DeviceState.READ:
            self._apply_read_progress(self.runtime.read_step)
        elif state == DeviceState.READ_COMPLETE:
            pass  # set by _on_reader_complete
        elif state == DeviceState.SAVE:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.ON)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.ERROR1:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.ON)
        elif state == DeviceState.ERROR2:
            self.leds.set_pattern("green", PatternKind.SLOW)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.SLOW)
        elif state == DeviceState.ERROR3:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.ERROR3)
        elif state == DeviceState.CANCELLED:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
        elif state == DeviceState.SWEETP:
            self.leds.set_pattern("yellow", PatternKind.OFF)
        elif state == DeviceState.UPLOAD:
            # Driven by _tick_upload_leds each loop
            self.leds.all_off()
        elif state == DeviceState.SHUTDOWN:
            self.leds.set_pattern("green", PatternKind.SLOW)
            self.leds.set_pattern("red", PatternKind.SLOW)
            self.leds.set_pattern("yellow", PatternKind.OFF)
        self._apply_wlan_led()

    def _apply_wlan_led(self) -> None:
        if self.runtime.wlan == WlanStatus.CONNECTED:
            self.leds.set_pattern("blue", PatternKind.HEARTBEAT)
        else:
            self.leds.set_pattern("blue", PatternKind.OFF)

    def _led_self_test(self, led_ms: int, cycles: int = 2) -> None:
        delay = max(0.05, led_ms / 1000.0)
        log.info("LED self-test %sx G→Y→R→B (%sms each)", cycles, led_ms)
        for _ in range(max(1, cycles)):
            for name in LED_NAMES:
                self.leds.all_off()
                self.leds.set_pattern(name, PatternKind.ON)
                self.leds.tick()
                # Blocking sleep is OK during boot only; tests inject a no-op sleep.
                self._sleep(delay)
        self.leds.all_off()
        self.leds.tick()


# Back-compat name
HWSniffApp = HeadlessApp
