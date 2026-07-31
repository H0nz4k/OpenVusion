"""Live SweetP position-quality worker (read-only, no field captures)."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from elatec_uid_tool.ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from elatec_uid_tool.protocol import ElatecError, SerialCommunicationError

from .models import AppEvent
from .sweetp_scoring import (
    ScoringConfig,
    SweetPLiveSnapshot,
    SweetPSample,
    SweetPScorer,
    SweetPTrend,
)


@dataclass
class SweetPConfig:
    sample_interval_ms: float = 150.0
    window_size: int = 20
    short_window_size: int = 5
    trend_threshold: float = 5.0
    trend_hold_ms: int = 800
    good_quality_threshold: float = 85.0
    poor_quality_threshold: float = 50.0
    good_hold_ms: int = 3000
    min_samples_for_trend: int = 5
    min_samples_for_ok: int = 8
    latency_good_ms: float = 80.0
    latency_bad_ms: float = 600.0
    weight_success: float = 0.60
    weight_latency: float = 0.25
    weight_uid_consistency: float = 0.15
    use_latency: bool = True
    ui_update_ms: float = 150.0
    handshake_timeout_seconds: float = 2.0
    # Live probe depth (all read-only). Full block is slower on Pi 3.
    require_get_version: bool = True
    require_page_00: bool = False
    require_application_block: bool = False
    # Legacy keys kept for merge compatibility (ignored by live loop).
    probe_attempts: int = 10
    probe_interval_ms: float = 100.0
    minimum_success_ratio: float = 0.9
    minimum_consecutive_successes: int = 5
    require_stable_uid: bool = True
    auto_repeat_seconds: float = 0.5


def _parse_sweetp_config(config: dict[str, Any]) -> SweetPConfig:
    sweet = config.get("sweetp") or {}
    reader = config.get("reader") or {}
    # Back-compat: older probe_interval_ms maps to sample_interval_ms.
    sample_interval = float(
        sweet.get("sample_interval_ms", sweet.get("probe_interval_ms", 150))
    )
    sample_interval = max(80.0, min(500.0, sample_interval))

    use_latency = bool(sweet.get("use_latency", True))
    w_s = float(sweet.get("weight_success", 0.60 if use_latency else 0.80))
    w_l = float(sweet.get("weight_latency", 0.25 if use_latency else 0.0))
    w_u = float(sweet.get("weight_uid_consistency", 0.15 if use_latency else 0.20))

    return SweetPConfig(
        sample_interval_ms=sample_interval,
        window_size=max(5, int(sweet.get("window_size", 20))),
        short_window_size=max(3, int(sweet.get("short_window_size", 5))),
        trend_threshold=float(sweet.get("trend_threshold", 5.0)),
        trend_hold_ms=max(0, int(sweet.get("trend_hold_ms", 800))),
        good_quality_threshold=float(sweet.get("good_quality_threshold", 85.0)),
        poor_quality_threshold=float(sweet.get("poor_quality_threshold", 50.0)),
        good_hold_ms=max(0, int(sweet.get("good_hold_ms", 3000))),
        min_samples_for_trend=max(3, int(sweet.get("min_samples_for_trend", 5))),
        min_samples_for_ok=max(3, int(sweet.get("min_samples_for_ok", 8))),
        latency_good_ms=float(sweet.get("latency_good_ms", 80.0)),
        latency_bad_ms=float(sweet.get("latency_bad_ms", 600.0)),
        weight_success=w_s,
        weight_latency=w_l,
        weight_uid_consistency=w_u,
        use_latency=use_latency,
        ui_update_ms=max(50.0, float(sweet.get("ui_update_ms", 150.0))),
        handshake_timeout_seconds=float(
            reader.get("handshake_timeout_seconds", 2)
        ),
        require_get_version=bool(sweet.get("require_get_version", True)),
        require_page_00=bool(sweet.get("require_page_00", False)),
        require_application_block=bool(
            sweet.get("require_application_block", False)
        ),
    )


class SweetPService:
    """Continuous live position-quality probe outside the UI thread."""

    def __init__(
        self,
        events: queue.Queue,
        *,
        client_factory: Callable | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.events = events
        self._client_factory = client_factory
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._port: str | None = None
        self._config = SweetPConfig()
        self._scorer: SweetPScorer | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, config: dict[str, Any]) -> None:
        if self.running:
            return
        self._config = _parse_sweetp_config(config)
        scoring = ScoringConfig(
            window_size=self._config.window_size,
            short_window_size=self._config.short_window_size,
            trend_threshold=self._config.trend_threshold,
            trend_hold_ms=self._config.trend_hold_ms,
            good_quality_threshold=self._config.good_quality_threshold,
            poor_quality_threshold=self._config.poor_quality_threshold,
            good_hold_ms=self._config.good_hold_ms,
            min_samples_for_trend=self._config.min_samples_for_trend,
            min_samples_for_ok=self._config.min_samples_for_ok,
            latency_good_ms=self._config.latency_good_ms,
            latency_bad_ms=self._config.latency_bad_ms,
            weight_success=self._config.weight_success,
            weight_latency=self._config.weight_latency,
            weight_uid_consistency=self._config.weight_uid_consistency,
            use_latency=self._config.use_latency,
        )
        self._scorer = SweetPScorer(scoring, clock=self._clock)
        self._port = port
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hwsniff-sweetp",
            daemon=True,
        )
        self._thread.start()
        self._emit("sweetp_started", port=port)

    def cancel(self, *, join_timeout: float = 5.0) -> None:
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        self._thread = None
        self._emit("sweetp_stopped")

    def request_retry(self) -> None:
        """Restart live scoring after a reader recovery (same worker restart)."""
        return None

    def _factory(self):
        if self._client_factory:
            return self._client_factory
        from elatec_uid_tool.protocol import SimpleProtocolClient

        return lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)

    def _emit(self, name: str, **payload: Any) -> None:
        # Bound queue growth: drop oldest non-critical live updates if flooded.
        if name == "sweetp_live" and self.events.qsize() > 32:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
        self.events.put(AppEvent(name=name, payload=payload))

    def _run(self) -> None:
        assert self._port is not None and self._scorer is not None
        cfg = self._config
        factory = self._factory()
        last_ui = 0.0
        last_quality_bucket = -1
        last_trend = SweetPTrend.STABLE
        last_position_ok = False
        sample_index = 0

        try:
            self._emit("sweetp_waiting")
            with factory(self._port, cfg.handshake_timeout_seconds) as client:
                while not self._cancel.is_set():
                    started = self._clock()
                    ok, uid, reason = self._probe_once(client)
                    latency_ms = max(0.0, (self._clock() - started) * 1000.0)
                    sample_index += 1
                    snap = self._scorer.add_sample(
                        SweetPSample(
                            success=ok,
                            uid=uid,
                            latency_ms=latency_ms,
                            monotonic_ts=started,
                        )
                    )
                    self._maybe_log_sample(sample_index, snap, ok, uid, latency_ms, reason)

                    quality_bucket = int(snap.current_quality // 5)
                    if quality_bucket != last_quality_bucket:
                        self._emit(
                            "sweetp_quality_changed",
                            quality=snap.current_quality,
                            best=snap.best_quality,
                        )
                        last_quality_bucket = quality_bucket
                    if snap.trend != last_trend:
                        self._emit(
                            "sweetp_trend_changed",
                            trend=snap.trend.value,
                            quality=snap.current_quality,
                        )
                        last_trend = snap.trend
                    if snap.position_ok and not last_position_ok:
                        self._emit(
                            "sweetp_good_position_entered",
                            quality=snap.current_quality,
                            uid=snap.dominant_uid,
                        )
                    elif not snap.position_ok and last_position_ok:
                        self._emit(
                            "sweetp_good_position_lost",
                            quality=snap.current_quality,
                        )
                    last_position_ok = snap.position_ok

                    now = self._clock()
                    if (now - last_ui) * 1000.0 >= cfg.ui_update_ms:
                        self._emit_live(snap)
                        last_ui = now

                    elapsed = self._clock() - started
                    wait = (cfg.sample_interval_ms / 1000.0) - elapsed
                    if wait > 0 and not self._cancel.is_set():
                        self._sleep(wait)

            self._emit("sweetp_finished", **self._live_payload(self._scorer.snapshot()))
        except (SerialCommunicationError, ElatecError, OSError) as exc:
            self._emit("sweetp_reader_error", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self._emit("sweetp_reader_error", error=str(exc))
        finally:
            if self._cancel.is_set():
                self._emit("sweetp_cancelled")

    def _emit_live(self, snap: SweetPLiveSnapshot) -> None:
        self._emit("sweetp_live", **self._live_payload(snap))

    def _live_payload(self, snap: SweetPLiveSnapshot) -> dict[str, Any]:
        return {
            "current_quality": snap.current_quality,
            "best_quality": snap.best_quality,
            "trend": snap.trend.value,
            "window_successes": snap.window_successes,
            "window_total": snap.window_total,
            "total_successes": snap.total_successes,
            "total_failures": snap.total_failures,
            "dominant_uid": snap.dominant_uid,
            "uid_consistency": snap.uid_consistency,
            "average_latency_ms": snap.average_latency_ms,
            "stable_duration_ms": snap.stable_duration_ms,
            "enough_samples": snap.enough_samples,
            "position_ok": snap.position_ok,
            "latency_available": snap.latency_available,
            "poor": snap.current_quality < self._config.poor_quality_threshold,
        }

    def _maybe_log_sample(
        self,
        index: int,
        snap: SweetPLiveSnapshot,
        ok: bool,
        uid: str | None,
        latency_ms: float,
        reason: str | None,
    ) -> None:
        # Periodic summary every 10 samples to avoid log flood.
        if index == 1 or index % 10 == 0:
            self._emit(
                "sweetp_sample",
                index=index,
                ok=ok,
                uid=uid,
                latency_ms=round(latency_ms, 1),
                quality=round(snap.current_quality, 1),
                reason=reason,
            )

    def _probe_once(
        self, client: Any
    ) -> tuple[bool, str | None, str | None]:
        cfg = self._config
        try:
            tag = client.search_tag()
            if tag is None:
                return False, None, "no_tag"
            uid = tag.id_hex
            ntag = NtagI2CPlus(client)
            if cfg.require_get_version:
                ntag.get_version()
            if cfg.require_page_00:
                ntag.read_page(0x00)
            if cfg.require_application_block:
                block = ntag.read_eeprom_range(
                    EEPROM_WATCH_START_PAGE,
                    EEPROM_WATCH_END_PAGE,
                )
                if len(block) != 32:
                    return False, uid, "app_block_length"
            return True, uid, None
        except SerialCommunicationError as exc:
            text = str(exc).lower()
            if "timeout" in text or "neodpověděl" in text:
                return False, None, "timeout"
            return False, None, str(exc)[:60]
        except (ElatecError, OSError):
            raise
        except Exception as exc:  # noqa: BLE001
            return False, None, str(exc)[:60]
