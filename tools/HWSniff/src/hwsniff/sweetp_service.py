from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from elatec_uid_tool.ntag import (
    EEPROM_WATCH_END_PAGE,
    EEPROM_WATCH_START_PAGE,
    NtagI2CPlus,
)
from elatec_uid_tool.protocol import ElatecError, SerialCommunicationError

from .models import AppEvent


@dataclass
class SweetPConfig:
    probe_attempts: int = 10
    probe_interval_ms: float = 100.0
    minimum_success_ratio: float = 0.9
    minimum_consecutive_successes: int = 5
    require_stable_uid: bool = True
    require_get_version: bool = True
    require_page_00: bool = True
    require_application_block: bool = True
    auto_repeat_seconds: float = 0.5
    handshake_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 0.15
    # Communication-quality thresholds (not RF field-strength estimates).
    excessive_reselect_ratio: float = 0.4
    excessive_timeout_ratio: float = 0.3


@dataclass
class SweetPMetrics:
    attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    consecutive_successes_max: int = 0
    success_ratio: float = 0.0
    observed_uids: list[str] = field(default_factory=list)
    uid_stable: bool = False
    get_version_success_count: int = 0
    page_00_success_count: int = 0
    application_block_success_count: int = 0
    timeout_count: int = 0
    reselect_count: int = 0
    reader_reconnect_count: int = 0
    probe_duration_min_ms: float | None = None
    probe_duration_avg_ms: float | None = None
    probe_duration_max_ms: float | None = None
    quality: str = "POOR"  # GOOD | USABLE | POOR — communication quality
    position_ok: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SweetPService:
    """Background read-only position probe (no field captures)."""

    def __init__(
        self,
        events: queue.Queue,
        *,
        client_factory: Callable | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.events = events
        self._client_factory = client_factory
        self._sleep = sleep or time.sleep
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._retry = threading.Event()
        self._port: str | None = None
        self._config = SweetPConfig()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, config: dict[str, Any]) -> None:
        if self.running:
            return
        sweet = config.get("sweetp") or {}
        reader = config.get("reader") or {}
        self._config = SweetPConfig(
            probe_attempts=int(sweet.get("probe_attempts", 10)),
            probe_interval_ms=float(sweet.get("probe_interval_ms", 100)),
            minimum_success_ratio=float(sweet.get("minimum_success_ratio", 0.9)),
            minimum_consecutive_successes=int(
                sweet.get("minimum_consecutive_successes", 5)
            ),
            require_stable_uid=bool(sweet.get("require_stable_uid", True)),
            require_get_version=bool(sweet.get("require_get_version", True)),
            require_page_00=bool(sweet.get("require_page_00", True)),
            require_application_block=bool(
                sweet.get("require_application_block", True)
            ),
            auto_repeat_seconds=float(sweet.get("auto_repeat_seconds", 0.5)),
            handshake_timeout_seconds=float(
                reader.get("handshake_timeout_seconds", 2)
            ),
        )
        self._port = port
        self._cancel.clear()
        self._retry.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hwsniff-sweetp",
            daemon=True,
        )
        self._thread.start()
        self._emit("sweetp_started", port=port)

    def cancel(self, *, join_timeout: float = 5.0) -> None:
        self._cancel.set()
        self._retry.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        self._thread = None
        self._emit("sweetp_stopped")

    def request_retry(self) -> None:
        self._retry.set()

    def _factory(self):
        if self._client_factory:
            return self._client_factory
        from elatec_uid_tool.protocol import SimpleProtocolClient

        return lambda port, timeout: SimpleProtocolClient(port, timeout=timeout)

    def _emit(self, name: str, **payload: Any) -> None:
        self.events.put(AppEvent(name=name, payload=payload))

    def _run(self) -> None:
        assert self._port is not None
        cfg = self._config
        factory = self._factory()
        try:
            while not self._cancel.is_set():
                self._emit("sweetp_waiting")
                tag_uid = self._wait_for_tag(factory)
                if self._cancel.is_set() or tag_uid is None:
                    break
                self._emit(
                    "sweetp_checking",
                    uid=tag_uid,
                    attempt=0,
                    total=cfg.probe_attempts,
                )
                metrics = self._run_probe_cycle(factory)
                self._emit(
                    "sweetp_result",
                    uid=(metrics.observed_uids[0] if metrics.observed_uids else tag_uid),
                    position_ok=metrics.position_ok,
                    quality=metrics.quality,
                    metrics=metrics.to_dict(),
                    reasons=metrics.reasons,
                )
                if self._cancel.is_set():
                    break
                # Wait for removal or ZNOVU / cancel from UI.
                self._wait_after_result(factory)
                if self._cancel.is_set():
                    break
                self._sleep(cfg.auto_repeat_seconds)
        except (SerialCommunicationError, ElatecError, OSError) as exc:
            self._emit("sweetp_reader_error", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self._emit("sweetp_reader_error", error=str(exc))
        finally:
            if self._cancel.is_set():
                self._emit("sweetp_cancelled")

    def _wait_for_tag(self, factory) -> str | None:
        cfg = self._config
        while not self._cancel.is_set():
            try:
                with factory(self._port, cfg.handshake_timeout_seconds) as client:
                    tag = client.search_tag()
                    if tag is not None:
                        return tag.id_hex
            except (SerialCommunicationError, ElatecError, OSError) as exc:
                self._emit("sweetp_reader_error", error=str(exc))
                return None
            self._sleep(cfg.poll_interval_seconds)
        return None

    def _wait_after_result(self, factory) -> None:
        cfg = self._config
        self._retry.clear()
        while not self._cancel.is_set() and not self._retry.is_set():
            try:
                with factory(self._port, cfg.handshake_timeout_seconds) as client:
                    tag = client.search_tag()
                    if tag is None:
                        return
            except (SerialCommunicationError, ElatecError, OSError):
                self._emit("sweetp_reader_error", error="reader lost after result")
                return
            self._sleep(cfg.poll_interval_seconds)

    def _run_probe_cycle(self, factory) -> SweetPMetrics:
        cfg = self._config
        metrics = SweetPMetrics()
        consecutive = 0
        durations: list[float] = []
        uids: set[str] = set()
        versions: set[str] = set()
        pages: set[str] = set()
        apps: set[str] = set()

        for index in range(1, cfg.probe_attempts + 1):
            if self._cancel.is_set():
                break
            metrics.attempts += 1
            self._emit(
                "sweetp_attempt",
                attempt=index,
                total=cfg.probe_attempts,
            )
            started = time.monotonic()
            ok, detail = self._probe_once(factory, metrics)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            durations.append(elapsed_ms)
            if ok:
                metrics.successful_attempts += 1
                consecutive += 1
                metrics.consecutive_successes_max = max(
                    metrics.consecutive_successes_max, consecutive
                )
                if detail.get("uid"):
                    uids.add(detail["uid"])
                    if detail["uid"] not in metrics.observed_uids:
                        metrics.observed_uids.append(detail["uid"])
                if detail.get("version"):
                    versions.add(detail["version"])
                    metrics.get_version_success_count += 1
                if detail.get("page00"):
                    pages.add(detail["page00"])
                    metrics.page_00_success_count += 1
                if detail.get("app"):
                    apps.add(detail["app"])
                    metrics.application_block_success_count += 1
            else:
                metrics.failed_attempts += 1
                consecutive = 0
                reason = detail.get("reason")
                if reason and reason not in metrics.reasons:
                    metrics.reasons.append(reason)

            if index < cfg.probe_attempts and not self._cancel.is_set():
                self._sleep(cfg.probe_interval_ms / 1000.0)

        if durations:
            metrics.probe_duration_min_ms = min(durations)
            metrics.probe_duration_max_ms = max(durations)
            metrics.probe_duration_avg_ms = sum(durations) / len(durations)

        if metrics.attempts:
            metrics.success_ratio = metrics.successful_attempts / metrics.attempts
        metrics.uid_stable = len(uids) <= 1 and metrics.successful_attempts > 0

        metrics.position_ok = self._evaluate_ok(
            metrics, uids, versions, pages, apps
        )
        metrics.quality = self._classify_quality(metrics)
        return metrics

    def _evaluate_ok(
        self,
        metrics: SweetPMetrics,
        uids: set[str],
        versions: set[str],
        pages: set[str],
        apps: set[str],
    ) -> bool:
        cfg = self._config
        if metrics.attempts == 0:
            metrics.reasons.append("no attempts")
            return False
        if metrics.success_ratio < cfg.minimum_success_ratio:
            metrics.reasons.append("success ratio below limit")
            return False
        if metrics.consecutive_successes_max < cfg.minimum_consecutive_successes:
            metrics.reasons.append("consecutive successes below limit")
            return False
        if cfg.require_stable_uid and (not metrics.uid_stable or len(uids) != 1):
            metrics.reasons.append("UID unstable")
            return False
        if cfg.require_get_version:
            if metrics.get_version_success_count < metrics.successful_attempts:
                metrics.reasons.append("GET_VERSION incomplete")
                return False
            if len(versions) != 1:
                metrics.reasons.append("GET_VERSION inconsistent")
                return False
        if cfg.require_page_00:
            if metrics.page_00_success_count < metrics.successful_attempts:
                metrics.reasons.append("page 0x00 incomplete")
                return False
            if len(pages) != 1:
                metrics.reasons.append("page 0x00 inconsistent")
                return False
        if cfg.require_application_block:
            if metrics.application_block_success_count < metrics.successful_attempts:
                metrics.reasons.append("application block incomplete")
                return False
            if len(apps) != 1:
                metrics.reasons.append("application block inconsistent")
                return False
            # Each app hex is 32 bytes → 64 hex chars without spaces.
            app_hex = next(iter(apps))
            if len(bytes.fromhex(app_hex)) != 32:
                metrics.reasons.append("application block length != 32")
                return False
        if metrics.attempts and (
            metrics.reselect_count / metrics.attempts > cfg.excessive_reselect_ratio
        ):
            metrics.reasons.append("excessive reselect")
            return False
        if metrics.attempts and (
            metrics.timeout_count / metrics.attempts > cfg.excessive_timeout_ratio
        ):
            metrics.reasons.append("excessive timeouts")
            return False
        if metrics.reader_reconnect_count > 0:
            metrics.reasons.append("reader reconnect during probe")
            return False
        return True

    def _classify_quality(self, metrics: SweetPMetrics) -> str:
        if metrics.position_ok and metrics.success_ratio >= 0.95:
            return "GOOD"
        if metrics.success_ratio >= 0.7 and metrics.consecutive_successes_max >= 3:
            return "USABLE"
        return "POOR"

    def _probe_once(
        self, factory, metrics: SweetPMetrics
    ) -> tuple[bool, dict[str, str]]:
        cfg = self._config
        detail: dict[str, str] = {}
        try:
            with factory(self._port, cfg.handshake_timeout_seconds) as client:
                tag = client.search_tag()
                if tag is None:
                    metrics.reselect_count += 1
                    return False, {"reason": "tag lost / reselect"}
                detail["uid"] = tag.id_hex
                ntag = NtagI2CPlus(client)
                if cfg.require_get_version:
                    version = ntag.get_version()
                    detail["version"] = version.raw.hex(" ").upper()
                if cfg.require_page_00:
                    page00 = ntag.read_page(0x00)
                    detail["page00"] = page00.hex(" ").upper()
                if cfg.require_application_block:
                    block = ntag.read_eeprom_range(
                        EEPROM_WATCH_START_PAGE,
                        EEPROM_WATCH_END_PAGE,
                    )
                    if len(block) != 32:
                        return False, {"reason": "application block length"}
                    detail["app"] = block.hex()
                return True, detail
        except SerialCommunicationError as exc:
            text = str(exc).lower()
            if "timeout" in text or "neodpověděl" in text:
                metrics.timeout_count += 1
                return False, {"reason": "timeout"}
            metrics.reselect_count += 1
            return False, {"reason": str(exc)[:80]}
        except (ElatecError, OSError) as exc:
            metrics.reader_reconnect_count += 1
            return False, {"reason": f"reader error: {exc}"[:80]}
        except Exception as exc:  # noqa: BLE001
            return False, {"reason": str(exc)[:80]}
