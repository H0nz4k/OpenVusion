"""Headless HWSniff orchestrator for Pi Zero 2 W (GPIO + LEDs, no GUI)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from .buttons import ButtonConfig, ButtonEvent, ButtonWatcher
from .collector_service import CollectorResult, MockCollector
from .configuration import DEFAULT_CONFIG, deep_merge, load_config
from .dip import DipReader
from .gpio_backend import GpioBackend, create_backend
from .health import run_health_checks
from .leds import LED_NAMES, LedController, LedPins
from .logging_setup import setup_logging
from .network import NetworkMonitor
from .patterns import PatternKind, PatternTimings
from .state import (
    CollectorOutcome,
    DeviceState,
    DipMode,
    RuntimeState,
    SweetQuality,
    WlanStatus,
)
from .sweet_point import MockSweetPoint, quality_to_led_levels

log = logging.getLogger(__name__)


class HeadlessApp:
    """Alpha1: GPIO / MAIN+SWEET_POINT state machine; mock capture + MockSweetPoint."""

    def __init__(
        self,
        config: dict[str, Any] | Path | None = None,
        *,
        gpio: GpioBackend | None = None,
        collector: MockCollector | None = None,
        sweet_point: MockSweetPoint | None = None,
        shutdown_callback: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        network: NetworkMonitor | None = None,
        loop_forever: bool = True,
    ) -> None:
        if isinstance(config, Path):
            self.config = load_config(config)
        elif config is None:
            self.config = deep_merge(DEFAULT_CONFIG, {})
        else:
            self.config = deep_merge(DEFAULT_CONFIG, config)

        self._clock = clock
        self._sleep = sleep
        self._loop_forever = loop_forever
        self._shutdown_callback = shutdown_callback or (lambda: None)
        self._stop_loop = False

        gpio_cfg = self.config.get("gpio") or {}
        btn_cfg = gpio_cfg.get("buttons") or {}
        dip_cfg = gpio_cfg.get("dip") or {}
        led_cfg = gpio_cfg.get("leds") or {}
        pat_cfg = self.config.get("led_patterns") or {}
        net_cfg = self.config.get("network") or {}

        prefer_mock = bool(self.config.get("gpio_prefer_mock"))
        self.gpio = gpio or create_backend(prefer_mock=prefer_mock)
        self.runtime = RuntimeState()

        timings = PatternTimings(
            slow_ms=int(pat_cfg.get("slow_ms", 500)),
            fast_ms=int(pat_cfg.get("fast_ms", 100)),
            single_flash_ms=int(pat_cfg.get("single_flash_ms", 150)),
            double_flash_ms=int(pat_cfg.get("double_flash_ms", 150)),
            triple_flash_ms=int(pat_cfg.get("triple_flash_ms", 100)),
        )
        self.leds = LedController(
            self.gpio,
            LedPins(
                green=int(led_cfg.get("green", 5)),
                yellow=int(led_cfg.get("yellow", 6)),
                red=int(led_cfg.get("red", 12)),
                blue=int(led_cfg.get("blue", 13)),
                orange=int(led_cfg.get("orange", 19)),
                active_high=bool(led_cfg.get("active_high", True)),
            ),
        )
        self.leds.engine.timings = timings
        self.leds.engine._clock = self._clock

        self.buttons = ButtonWatcher(
            self.gpio,
            ButtonConfig(
                start_pin=int(btn_cfg.get("start", 17)),
                stop_pin=int(btn_cfg.get("stop", 27)),
                active_low=bool(btn_cfg.get("active_low", True)),
                pull_up=bool(btn_cfg.get("pull_up", True)),
                debounce_ms=int(btn_cfg.get("debounce_ms", 50)),
                shutdown_hold_seconds=float(
                    btn_cfg.get("shutdown_hold_seconds", 3)
                ),
            ),
            clock=self._clock,
        )
        self.dip = DipReader(
            self.gpio,
            dip1_pin=int(dip_cfg.get("dip1", 22)),
            dip2_pin=int(dip_cfg.get("dip2", 18)),
            active_low=bool(dip_cfg.get("active_low", True)),
            pull_up=bool(dip_cfg.get("pull_up", True)),
        )
        self.network = network or NetworkMonitor(
            interface=str(net_cfg.get("interface", "wlan0")),
            poll_seconds=float(net_cfg.get("poll_seconds", 3)),
            clock=self._clock,
        )
        mock_cfg = self.config.get("mock_collector") or {}
        self.collector = collector or MockCollector(
            work_seconds=float(mock_cfg.get("work_seconds", 2.0)),
            save_seconds=float(mock_cfg.get("save_seconds", 0.3)),
            outcome=CollectorOutcome(
                mock_cfg.get("outcome", CollectorOutcome.SUCCESS.value)
            ),
            clock=self._clock,
        )
        self.collector.on_phase = self._on_collector_phase

        sweet_cfg = self.config.get("mock_sweet_point") or {}
        self.sweet_point = sweet_point or MockSweetPoint(
            period_seconds=float(sweet_cfg.get("period_seconds", 1.0)),
            clock=self._clock,
        )

        self._pending_timer: float | None = None
        self._pending_action: str | None = None
        self._gpio_ok = True
        self._cancel_phase: str | None = None

    # ------------------------------------------------------------------ lifecycle

    def run(self) -> int:
        log_root = Path(self.config.get("log_root", "/var/log/hwsniff"))
        try:
            setup_logging(log_root)
        except Exception:  # noqa: BLE001
            logging.basicConfig(level=logging.INFO)
        log.info("HWSniff headless boot (Pi Zero GPIO alpha1)")
        try:
            self.boot()
        except Exception as exc:  # noqa: BLE001
            log.exception("Boot failed")
            self._gpio_ok = False
            self._enter(DeviceState.ERROR, error=str(exc))
        while not self._stop_loop:
            self.tick()
            if not self._loop_forever:
                break
            self._sleep(0.02)
        self.close()
        return 0 if self.runtime.device_state != DeviceState.ERROR else 1

    def close(self) -> None:
        try:
            self.sweet_point.stop()
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
        d1, d2 = self.dip.read_raw()
        self.runtime.dip_mode = DipMode.SWEET_POINT if d1 else DipMode.MAIN
        self.runtime.dip2_reserved_on = d2
        log.info(
            "DIP at boot: mode=%s dip2_reserved=%s",
            self.runtime.dip_mode.value,
            "ON" if d2 else "OFF",
        )
        self_test = self.config.get("self_test") or {}
        if bool(self_test.get("enabled", True)):
            self._led_self_test(int(self_test.get("led_ms", 180)))
        self.network.tick(self._clock())
        self.runtime.wlan = self.network.status
        self.runtime.wlan_ip = self.network.ip
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
            require_wlan=False,
            wlan_connected=self.runtime.wlan == WlanStatus.CONNECTED,
        )
        if not report.ok:
            self._enter(DeviceState.ERROR, error=";".join(report.errors))
            return
        # Prime button baseline before READY so a stuck STOP at power-on
        # cannot arm long-press, while a later edge still works.
        _ = self.buttons.poll()
        if self.runtime.dip_mode == DipMode.SWEET_POINT:
            self._enter_sweet_point()
        else:
            self._enter(DeviceState.READY)

    def tick(self) -> None:
        now = self._clock()
        if self.network.tick(now):
            self.runtime.wlan = self.network.status
            self.runtime.wlan_ip = self.network.ip
            self._apply_wlan_led()

        # DIP has higher priority than START / button handling
        self._poll_dip()

        for ev in self.buttons.poll():
            self._handle_button(ev)

        if self.runtime.device_state == DeviceState.SWEET_POINT:
            self._tick_sweet_point(now)
        else:
            self.collector.tick(now)
            self._poll_collector()

        self._poll_timers(now)
        self.leds.tick(now)

    # ------------------------------------------------------------------ DIP

    def _poll_dip(self) -> None:
        d1, d2 = self.dip.read_raw()
        self.runtime.dip2_reserved_on = d2
        wanted = DipMode.SWEET_POINT if d1 else DipMode.MAIN
        if wanted == self.runtime.dip_mode:
            return
        prev = self.runtime.dip_mode
        self.runtime.dip_mode = wanted
        log.info("DIP mode %s → %s (priority over START)", prev.value, wanted.value)
        if wanted == DipMode.SWEET_POINT:
            self._abort_main_for_sweet()
            self._enter_sweet_point()
        else:
            self._leave_sweet_point_to_main()

    def _abort_main_for_sweet(self) -> None:
        """Stop any MAIN capture when entering Sweet Point."""
        self._pending_timer = None
        self._pending_action = None
        self._cancel_phase = None
        if self.collector.is_running():
            self.collector.request_stop()
            # Drain cancelled result without entering CANCELLED UI sequence
            self.collector.tick(self._clock())
            _ = self.collector.get_result()
        self.runtime.active_cycle_mode = None
        self.runtime.collector_running = False

    def _enter_sweet_point(self) -> None:
        self.sweet_point.start()
        self._enter(DeviceState.SWEET_POINT)

    def _leave_sweet_point_to_main(self) -> None:
        self.sweet_point.stop()
        self.runtime.sweet_quality = SweetQuality.NONE
        self.runtime.sweet_score = None
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
            require_wlan=False,
            wlan_connected=self.runtime.wlan == WlanStatus.CONNECTED,
        )
        if not report.ok:
            self._enter(DeviceState.ERROR, error=";".join(report.errors))
            return
        self._enter(DeviceState.READY)

    def _tick_sweet_point(self, now: float) -> None:
        sample = self.sweet_point.tick(now)
        self.runtime.sweet_quality = sample.quality
        self.runtime.sweet_score = sample.score
        self._apply_sweet_leds(sample.quality)

    def _apply_sweet_leds(self, quality: SweetQuality) -> None:
        levels = quality_to_led_levels(quality)
        self.leds.set_pattern(
            "green", PatternKind.ON if levels["green"] else PatternKind.OFF
        )
        self.leds.set_pattern(
            "orange", PatternKind.ON if levels["orange"] else PatternKind.OFF
        )
        self.leds.set_pattern(
            "red", PatternKind.ON if levels["red"] else PatternKind.OFF
        )
        self.leds.set_pattern("yellow", PatternKind.OFF)
        self._apply_wlan_led()

    # ------------------------------------------------------------------ buttons

    def _handle_button(self, ev: ButtonEvent) -> None:
        st = self.runtime.device_state
        log.info("Button %s in %s", ev.value, st.value)

        if st == DeviceState.SWEET_POINT:
            # START/STOP ignored — Sweet Point is DIP-controlled; power is hardware switch
            return

        if st == DeviceState.SUCCESS_WAIT_ACK:
            # START/STOP only acknowledge — never start a new capture here
            if ev in (
                ButtonEvent.START_SHORT,
                ButtonEvent.STOP_SHORT,
                ButtonEvent.STOP_LONG,
            ):
                self._ack_success()
            return

        if ev == ButtonEvent.START_SHORT:
            if st == DeviceState.READY:
                self._begin_waiting()
            elif st == DeviceState.WAITING:
                # Alpha1: second START simulates TAG DETECTED
                self._begin_reading()
            elif st in (DeviceState.PARTIAL, DeviceState.ERROR):
                if st == DeviceState.ERROR:
                    report = run_health_checks(gpio_ok=self._gpio_ok)
                    if not report.ok:
                        log.warning("Still unhealthy: %s", report.errors)
                        return
                self._begin_waiting()
            return

        if ev == ButtonEvent.STOP_SHORT:
            if st == DeviceState.WAITING:
                self._begin_cancel_sequence()
            elif st == DeviceState.READING:
                self.collector.request_stop()
            elif st == DeviceState.PARTIAL:
                self._enter(DeviceState.READY)
            elif st == DeviceState.ERROR:
                self._enter(DeviceState.READY)
            return

        if ev == ButtonEvent.STOP_LONG:
            # 3 s hold: abort everything → back to MAIN READY (no poweroff;
            # power is a separate hardware switch).
            self._reset_main_to_ready()

    # ------------------------------------------------------------------ cycle

    def _begin_waiting(self) -> None:
        if self.runtime.dip_mode != DipMode.MAIN:
            log.info("START ignored — not in MAIN mode")
            return
        self.runtime.active_cycle_mode = DipMode.MAIN
        log.info("MAIN cycle started")
        self._enter(DeviceState.WAITING)

    def _begin_reading(self) -> None:
        if self.runtime.dip_mode != DipMode.MAIN:
            return
        self._enter(DeviceState.READING)
        self.collector.start(DipMode.MAIN)

    def _on_collector_phase(self, phase: str) -> None:
        if phase == "saving" and self.runtime.device_state == DeviceState.READING:
            self._enter(DeviceState.SAVING)

    def _poll_collector(self) -> None:
        if self.runtime.device_state not in (
            DeviceState.READING,
            DeviceState.SAVING,
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
        log.info("Collector result: %s (%s)", result.outcome.value, result.message)
        if result.outcome == CollectorOutcome.SUCCESS:
            self.runtime.active_cycle_mode = None
            self.runtime.collector_running = False
            self._enter(DeviceState.SUCCESS_WAIT_ACK)
        elif result.outcome == CollectorOutcome.PARTIAL:
            self._enter(DeviceState.PARTIAL)
        elif result.outcome == CollectorOutcome.CANCELLED:
            self._begin_cancel_sequence()
        else:
            self._enter(DeviceState.ERROR, error=result.message or "FAILED")

    def _ack_success(self) -> None:
        """User confirmed success; do not start a new capture from this press."""
        log.info("SUCCESS_WAIT_ACK acknowledged")
        self.leds.set_pattern("orange", PatternKind.OFF)
        report = run_health_checks(
            gpio_ok=self._gpio_ok,
            data_root=self.config.get("data_root"),
            require_wlan=False,
            wlan_connected=self.runtime.wlan == WlanStatus.CONNECTED,
        )
        if not report.ok:
            self._enter(DeviceState.ERROR, error=";".join(report.errors))
            return
        if self.runtime.dip_mode == DipMode.SWEET_POINT:
            self._enter_sweet_point()
            return
        self._enter(DeviceState.READY)

    def _begin_cancel_sequence(self) -> None:
        """Red short blink → green confirm blink → READY."""
        self._cancel_phase = "red"
        self._enter(DeviceState.CANCELLED)

    def _reset_main_to_ready(self) -> None:
        """Long STOP: stop collector / signals and return to start of MAIN."""
        st = self.runtime.device_state
        if st == DeviceState.READY:
            log.info("Long STOP in READY — already at MAIN start")
            return
        if st == DeviceState.SWEET_POINT:
            return
        log.info("Long STOP — abort and reset to MAIN READY")
        self._pending_timer = None
        self._pending_action = None
        if self.collector.is_running():
            self.collector.request_stop()
            self.collector.tick(self._clock())
            _ = self.collector.get_result()
        self.runtime.active_cycle_mode = None
        self.runtime.collector_running = False
        if st in (
            DeviceState.WAITING,
            DeviceState.READING,
            DeviceState.SAVING,
            DeviceState.CANCELLED,
        ):
            self._begin_cancel_sequence()
            return
        # PARTIAL / ERROR / other → straight back to READY
        if self.runtime.dip_mode == DipMode.SWEET_POINT:
            self._enter_sweet_point()
        else:
            self._enter(DeviceState.READY)

    # ------------------------------------------------------------------ timers / states

    def _schedule(self, delay_s: float, action: str) -> None:
        self._pending_timer = self._clock() + delay_s
        self._pending_action = action

    def _poll_timers(self, now: float) -> None:
        if self._pending_timer is None or self._pending_action is None:
            return
        if now < self._pending_timer:
            return
        action = self._pending_action
        self._pending_timer = None
        self._pending_action = None
        if action == "cancel_after_stop":
            self._begin_cancel_sequence()

    def _enter(self, state: DeviceState, *, error: str | None = None) -> None:
        prev = self.runtime.device_state
        self.runtime.device_state = state
        if error:
            self.runtime.last_error = error
        log.info("State %s → %s", prev.value, state.value)
        self._apply_state_leds(state)
        if state == DeviceState.CANCELLED:
            self._start_cancel_red_flash()
        elif state == DeviceState.SHUTDOWN:
            self._do_shutdown()

    def _start_cancel_red_flash(self) -> None:
        self.leds.set_pattern("green", PatternKind.OFF)
        self.leds.set_pattern("yellow", PatternKind.OFF)
        self.leds.set_pattern("orange", PatternKind.OFF)
        self.leds.set_pattern(
            "red",
            PatternKind.SINGLE,
            on_complete=self._cancel_green_confirm,
        )
        self._apply_wlan_led()

    def _cancel_green_confirm(self) -> None:
        if self.runtime.device_state != DeviceState.CANCELLED:
            return
        self._cancel_phase = "green"
        self.leds.set_pattern("red", PatternKind.OFF)
        self.leds.set_pattern(
            "green",
            PatternKind.SINGLE,
            on_complete=self._cancel_to_ready,
        )

    def _cancel_to_ready(self) -> None:
        if self.runtime.device_state != DeviceState.CANCELLED:
            return
        self._cancel_phase = None
        # DIP may have flipped during cancel — honour current mode
        if self.runtime.dip_mode == DipMode.SWEET_POINT:
            self._enter_sweet_point()
        else:
            self._enter(DeviceState.READY)

    def _apply_state_leds(self, state: DeviceState) -> None:
        if state == DeviceState.BOOT:
            self.leds.all_off()
        elif state == DeviceState.READY:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.WAITING:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.SLOW)
            self.leds.set_pattern("red", PatternKind.OFF)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.READING:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.FAST)
            self.leds.set_pattern("red", PatternKind.OFF)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.SAVING:
            self.leds.set_pattern("yellow", PatternKind.ON)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.SUCCESS_WAIT_ACK:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("orange", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.CANCELLED:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.PARTIAL:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.SLOW)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.ERROR:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.ON)
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif state == DeviceState.SWEET_POINT:
            self.leds.set_pattern("yellow", PatternKind.OFF)
            # quality LEDs applied by _tick_sweet_point / _apply_sweet_leds
        elif state == DeviceState.SHUTDOWN:
            self.leds.set_pattern("green", PatternKind.SLOW)
            self.leds.set_pattern("red", PatternKind.SLOW)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("orange", PatternKind.OFF)
        self._apply_wlan_led()

    def _apply_wlan_led(self) -> None:
        if self.runtime.wlan == WlanStatus.CONNECTED:
            self.leds.set_pattern("blue", PatternKind.ON)
        elif self.runtime.wlan == WlanStatus.CONNECTING:
            self.leds.set_pattern("blue", PatternKind.SLOW)
        else:
            self.leds.set_pattern("blue", PatternKind.OFF)

    def _led_self_test(self, led_ms: int) -> None:
        delay = max(0.05, led_ms / 1000.0)
        for name in LED_NAMES:
            self.leds.all_off()
            self.leds.set_pattern(name, PatternKind.ON)
            end = self._clock() + delay
            while self._clock() < end:
                self.leds.tick()
                self._sleep(0.01)
        self.leds.all_off()

    def _do_shutdown(self) -> None:
        """Legacy hook — GPIO long-STOP no longer powers off (hardware switch)."""
        log.warning("SHUTDOWN requested")
        try:
            self._shutdown_callback()
        except Exception:  # noqa: BLE001
            log.exception("shutdown callback failed")
        self._stop_loop = True


# Back-compat name used by some entrypoints
HWSniffApp = HeadlessApp
