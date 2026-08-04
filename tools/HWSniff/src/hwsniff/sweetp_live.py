"""Headless live SweetP worker using verified scoring + TWN4 probes."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .legacy.sweetp_scoring import (
    ScoringConfig,
    SweetPSample,
    SweetPScorer,
)
from .legacy.sweetp_service import _parse_sweetp_config
from .state import SweetBand
from .sweet_point import SweetSample
from .sweetp_bands import SweetPThresholds, band_from_score, thresholds_from_config

log = logging.getLogger(__name__)


class LiveSweetPoint:
    """Background SweetP probe; main loop reads latest sample via tick()."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client_factory: Callable | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config_doc = config
        self._sweet_cfg = _parse_sweetp_config(config)
        self._thresholds = thresholds_from_config(config.get("sweetp") or {})
        self._client_factory = client_factory
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._sample = SweetSample(None, SweetBand.NONE, False)
        self._port: str | None = None
        self._band = SweetBand.NONE
        self._reader_error: str | None = None
        self._running_idle = False

    def start(self, port: str | None = None) -> bool:
        if self.is_running():
            return True
        if not port:
            log.warning("LiveSweetPoint.start without port — refused")
            self._port = None
            self._running_idle = False
            self._reader_error = "no_reader_port"
            return False
        self._running_idle = False
        self._port = port
        self._cancel.clear()
        self._reader_error = None
        self._thread = threading.Thread(
            target=self._run, name="hwsniff-sweetp", daemon=True
        )
        self._thread.start()
        log.info("SweetP live started on %s", port)
        return True

    def stop(self) -> None:
        self._cancel.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
        self._running_idle = False
        self._reader_error = None
        with self._lock:
            self._sample = SweetSample(None, SweetBand.NONE, False)
            self._band = SweetBand.NONE
        log.info("SweetP live stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_sample(self) -> SweetSample:
        with self._lock:
            return self._sample

    @property
    def reader_error(self) -> str | None:
        return self._reader_error

    def tick(self, now: float | None = None) -> SweetSample:
        del now
        return self.get_sample()

    def _factory(self):
        if self._client_factory:
            return self._client_factory
        from elatec_uid_tool.protocol import SimpleProtocolClient

        return lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)

    def _set_sample(self, score: float | None, has_tag: bool) -> None:
        with self._lock:
            band = band_from_score(
                score,
                has_tag=has_tag,
                previous=self._band,
                thresholds=self._thresholds,
            )
            self._band = band
            self._sample = SweetSample(score, band, has_tag)

    def _run(self) -> None:
        assert self._port is not None
        cfg = self._sweet_cfg
        scoring = ScoringConfig(
            window_size=cfg.window_size,
            short_window_size=cfg.short_window_size,
            trend_threshold=cfg.trend_threshold,
            trend_hold_ms=cfg.trend_hold_ms,
            good_quality_threshold=cfg.good_quality_threshold,
            poor_quality_threshold=cfg.poor_quality_threshold,
            good_hold_ms=cfg.good_hold_ms,
            min_samples_for_trend=cfg.min_samples_for_trend,
            min_samples_for_ok=cfg.min_samples_for_ok,
            latency_good_ms=cfg.latency_good_ms,
            latency_bad_ms=cfg.latency_bad_ms,
            weight_success=cfg.weight_success,
            weight_latency=cfg.weight_latency,
            weight_uid_consistency=cfg.weight_uid_consistency,
            use_latency=cfg.use_latency,
        )
        scorer = SweetPScorer(scoring, clock=self._clock)
        factory = self._factory()

        try:
            with factory(self._port, cfg.handshake_timeout_seconds) as client:
                while not self._cancel.is_set():
                    started = self._clock()
                    ok, uid, _reason = self._probe_once(client)
                    latency_ms = max(0.0, (self._clock() - started) * 1000.0)
                    snap = scorer.add_sample(
                        SweetPSample(
                            success=ok,
                            uid=uid,
                            latency_ms=latency_ms,
                            monotonic_ts=started,
                        )
                    )
                    has_tag = bool(ok and uid)
                    score = snap.current_quality if has_tag or snap.window_total else None
                    if not has_tag and snap.window_successes == 0:
                        self._set_sample(None, False)
                    else:
                        self._set_sample(score, has_tag or snap.window_successes > 0)
                    elapsed = self._clock() - started
                    wait = (cfg.sample_interval_ms / 1000.0) - elapsed
                    if wait > 0 and not self._cancel.is_set():
                        self._sleep(wait)
        except Exception as exc:  # noqa: BLE001
            self._reader_error = str(exc)
            log.warning("SweetP reader error: %s", exc)
            self._set_sample(None, False)

    def _probe_once(self, client: Any) -> tuple[bool, str | None, str | None]:
        from elatec_uid_tool.ntag import NtagI2CPlus
        from elatec_uid_tool.protocol import ElatecError, SerialCommunicationError

        cfg = self._sweet_cfg
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
            return True, uid, None
        except SerialCommunicationError as exc:
            text = str(exc).lower()
            if "timeout" in text:
                return False, None, "timeout"
            return False, None, str(exc)[:60]
        except (ElatecError, OSError):
            raise
        except Exception as exc:  # noqa: BLE001
            return False, None, str(exc)[:60]


def create_sweet_point(
    config: dict[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    client_factory: Callable | None = None,
    force_mock: bool = False,
) -> Any:
    sweet = config.get("sweetp") or {}
    use_mock = force_mock or bool(sweet.get("use_mock")) or bool(
        config.get("gpio_prefer_mock")
    )
    if use_mock:
        from .sweet_point import mock_from_config

        return mock_from_config(config, clock=clock)
    return LiveSweetPoint(
        config,
        client_factory=client_factory,
        sleep=sleep,
        clock=clock,
    )
