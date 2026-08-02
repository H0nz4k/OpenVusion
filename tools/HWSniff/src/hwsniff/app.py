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
from .gpio_backend import GpioBackend, MockGpioBackend, create_backend
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
    WlanStatus,
)

log = logging.getLogger(__name__)


class HeadlessApp:
    """Alpha1: validate GPIO / state machine / WLAN; mock capture."""

    def __init__(
        self,
        config: dict[str, Any] | Path | None = None,
        *,
        gpio: GpioBackend | None = None,
        collector: MockCollector | None = None,
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
                    btn_cfg.get("shutdown_hold_seconds", 4)
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

        self._pending_timer: float | None = None
        self._pending_action: str | None = None
        self._gpio_ok = True

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
        self.runtime.dip_mode = self.dip.read_mode()
        log.info("DIP mode at boot: %s", self.runtime.dip_mode.value)
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
        self._enter(DeviceState.READY)

    def tick(self) -> None:
        now = self._clock()
        if self.network.tick(now):
            self.runtime.wlan = self.network.status
            self.runtime.wlan_ip = self.network.ip
            self._apply_wlan_led()
            self._apply_orange_led()

        for ev in self.buttons.poll():
            self._handle_button(ev)

        self.collector.tick(now)
        self._poll_collector()
        self._poll_timers(now)
        self.leds.tick(now)

    # ------------------------------------------------------------------ buttons

    def _handle_button(self, ev: ButtonEvent) -> None:
        st = self.runtime.device_state
        log.info("Button %s in %s", ev.value, st.value)

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
            # READING / SAVING / signals: ignore
            return

        if ev == ButtonEvent.STOP_SHORT:
            if st == DeviceState.WAITING:
                self._enter(DeviceState.CANCELLED)
            elif st == DeviceState.READING:
                self.collector.request_stop()
                # wait for collector result via poll
            elif st == DeviceState.PARTIAL:
                self._enter(DeviceState.READY)
            elif st == DeviceState.ERROR:
                self._enter(DeviceState.READY)
            return

        if ev == ButtonEvent.STOP_LONG:
            if st == DeviceState.READING:
                self.collector.request_stop()
                self._schedule(0.2, "shutdown_after_stop")
            elif st in (
                DeviceState.READY,
                DeviceState.ERROR,
                DeviceState.PARTIAL,
                DeviceState.WAITING,
            ):
                self._enter(DeviceState.SHUTDOWN)

    # ------------------------------------------------------------------ cycle

    def _begin_waiting(self) -> None:
        # Re-read DIP only at START of a new cycle
        self.runtime.dip_mode = self.dip.read_mode()
        self.runtime.active_cycle_mode = self.runtime.dip_mode
        log.info("Cycle mode locked: %s", self.runtime.active_cycle_mode.value)
        self._enter(DeviceState.WAITING)

    def _begin_reading(self) -> None:
        mode = self.runtime.active_cycle_mode or self.runtime.dip_mode
        self._enter(DeviceState.READING)
        self.collector.start(mode)

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
            self._enter(DeviceState.SUCCESS_SIGNAL)
        elif result.outcome == CollectorOutcome.PARTIAL:
            self._enter(DeviceState.PARTIAL)
        elif result.outcome == CollectorOutcome.CANCELLED:
            self._enter(DeviceState.CANCELLED)
        else:
            self._enter(DeviceState.ERROR, error=result.message or "FAILED")

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
        if action == "after_success":
            self._enter(DeviceState.READY)
        elif action == "after_cancelled":
            self._enter(DeviceState.READY)
        elif action == "shutdown_after_stop":
            self._enter(DeviceState.SHUTDOWN)
        elif action == "saving_hold":
            pass

    def _enter(self, state: DeviceState, *, error: str | None = None) -> None:
        prev = self.runtime.device_state
        self.runtime.device_state = state
        if error:
            self.runtime.last_error = error
        log.info("State %s → %s", prev.value, state.value)
        self._apply_state_leds(state)
        if state == DeviceState.SUCCESS_SIGNAL:
            # triple flash then READY via pattern callback
            self.leds.set_pattern(
                "green",
                PatternKind.TRIPLE,
                on_complete=lambda: self._enter(DeviceState.READY),
            )
        elif state == DeviceState.CANCELLED:
            self.leds.set_pattern(
                "red",
                PatternKind.DOUBLE,
                on_complete=lambda: self._enter(DeviceState.READY),
            )
        elif state == DeviceState.SHUTDOWN:
            self._do_shutdown()

    def _apply_state_leds(self, state: DeviceState) -> None:
        # Reset operational LEDs; WLAN/orange applied after
        if state == DeviceState.BOOT:
            self.leds.all_off()
        elif state == DeviceState.READY:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.WAITING:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.SLOW)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.READING:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.FAST)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.SAVING:
            self.leds.set_pattern("yellow", PatternKind.ON)
        elif state == DeviceState.SUCCESS_SIGNAL:
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.OFF)
        elif state == DeviceState.CANCELLED:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
        elif state == DeviceState.PARTIAL:
            self.leds.set_pattern("green", PatternKind.ON)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.SLOW)
        elif state == DeviceState.ERROR:
            self.leds.set_pattern("green", PatternKind.OFF)
            self.leds.set_pattern("yellow", PatternKind.OFF)
            self.leds.set_pattern("red", PatternKind.ON)
        elif state == DeviceState.SHUTDOWN:
            self.leds.set_pattern("green", PatternKind.SLOW)
            self.leds.set_pattern("red", PatternKind.SLOW)
            self.leds.set_pattern("yellow", PatternKind.OFF)
        self._apply_wlan_led()
        self._apply_orange_led()

    def _apply_wlan_led(self) -> None:
        if self.runtime.wlan == WlanStatus.CONNECTED:
            self.leds.set_pattern("blue", PatternKind.ON)
        elif self.runtime.wlan == WlanStatus.CONNECTING:
            self.leds.set_pattern("blue", PatternKind.SLOW)
        else:
            self.leds.set_pattern("blue", PatternKind.OFF)

    def _apply_orange_led(self) -> None:
        # Orange follows configured DIP mode (live), not mid-cycle lock —
        # except we still show current dip_mode which updates only on START/boot.
        # During READING, dip_mode is not re-read, so orange stays on cycle mode.
        mode = self.runtime.active_cycle_mode or self.runtime.dip_mode
        if mode == DipMode.NORMAL:
            self.leds.set_pattern("orange", PatternKind.OFF)
        elif mode == DipMode.FAST:
            self.leds.set_pattern("orange", PatternKind.ON)
        elif mode == DipMode.DEEP:
            self.leds.set_pattern("orange", PatternKind.SLOW)
        else:
            self.leds.set_pattern("orange", PatternKind.FAST)

    def _led_self_test(self, led_ms: int) -> None:
        delay = max(0.05, led_ms / 1000.0)
        for name in LED_NAMES:
            self.leds.all_off()
            self.leds.set_pattern(name, PatternKind.ON)
            # brief blocking OK only during boot self-test
            end = self._clock() + delay
            while self._clock() < end:
                self.leds.tick()
                self._sleep(0.01)
        self.leds.all_off()

    def _do_shutdown(self) -> None:
        log.warning("SHUTDOWN requested")
        try:
            self._shutdown_callback()
        except Exception:  # noqa: BLE001
            log.exception("shutdown callback failed")
        self._stop_loop = True


# Back-compat name used by some entrypoints
HWSniffApp = HeadlessApp
