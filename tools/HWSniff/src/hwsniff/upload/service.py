"""Single-threaded upload worker for DIP2 WiFi upload mode."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable

from .config import UploadSettings
from .ftp_client import BundleUploader, FtpErrorCategory
from .led_signals import UploadLedPattern, led_levels, pattern_finished
from .state_store import BundleRecord, BundleStatus, UploadStateStore
from .wifi import WifiCheck, check_wifi_ready

log = logging.getLogger(__name__)


class UploadPhase(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    SUCCESS = "success"
    EMPTY = "empty"
    NO_WIFI = "no_wifi"
    FTP_ERROR = "ftp_error"
    PARTIAL = "partial"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_export_bundles(
    source_root: Path,
    *,
    suffixes: tuple[str, ...] = (".tar", ".zip"),
) -> list[Path]:
    """Completed bundles only — ignore .tmp/.part and non-regular files."""
    root = Path(source_root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.iterdir():
        name = path.name
        if name.endswith(".tmp") or name.endswith(".part"):
            continue
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        lower = name.lower()
        if not any(lower.endswith(suf) for suf in suffixes):
            continue
        found.append(path)
    found.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return found


class UploadService:
    """Owns at most one worker thread; safe to start/stop from the app loop."""

    def __init__(
        self,
        settings: UploadSettings,
        *,
        store: UploadStateStore | None = None,
        uploader: BundleUploader | None = None,
        wifi_check: Callable[[str], WifiCheck] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.store = store or UploadStateStore(Path(settings.state_file))
        self.uploader = uploader or BundleUploader(settings)
        self._wifi_check = wifi_check or (
            lambda iface: check_wifi_ready(iface)
        )
        self._clock = clock
        self._sleep = sleep
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._phase = UploadPhase.IDLE
        self._phase_since = clock()
        self._oneshot_done = False
        self.store.load()

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    @property
    def phase(self) -> UploadPhase:
        return self._phase

    def start(self) -> None:
        with self._lock:
            if self.running:
                log.info("Upload already running — ignore duplicate start")
                return
            if not self.settings.enabled:
                log.warning("Upload disabled in config")
                return
            self._stop.clear()
            self._oneshot_done = False
            self._set_phase(UploadPhase.ACTIVE)
            self._thread = threading.Thread(
                target=self._run,
                name="hwsniff-upload",
                daemon=True,
            )
            self._thread.start()
            log.info(
                "Upload mode enter settings=%s",
                self.settings.safe_dict(),
            )

    def stop(self) -> None:
        log.info("Upload mode leave — stopping rescan/retry")
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
        with self._lock:
            self._thread = None
        self._set_phase(UploadPhase.IDLE)

    def led_levels(self) -> dict[str, bool]:
        pattern = _phase_to_pattern(self._phase)
        elapsed = max(0.0, self._clock() - self._phase_since)
        levels = led_levels(pattern, elapsed)
        # Advance one-shot patterns toward idle/active without blocking
        if pattern_finished(pattern, elapsed) and self.running:
            if self._phase in (
                UploadPhase.SUCCESS,
                UploadPhase.EMPTY,
                UploadPhase.PARTIAL,
            ):
                # After success/empty/partial show, settle to idle-in-mode (dark)
                # until next rescan; active resumes when work continues.
                if self._phase == UploadPhase.SUCCESS:
                    self._oneshot_done = True
                self._set_phase(UploadPhase.IDLE)
        return levels

    def _set_phase(self, phase: UploadPhase) -> None:
        if phase != self._phase:
            self._phase = phase
            self._phase_since = self._clock()

    def _run(self) -> None:
        retry_idx = 0
        while not self._stop.is_set():
            try:
                outcome = self._cycle_once()
            except Exception as exc:  # noqa: BLE001
                log.exception("Upload cycle error: %s", type(exc).__name__)
                outcome = "ftp_error"

            if self._stop.is_set():
                break

            if outcome == "success":
                self._set_phase(UploadPhase.SUCCESS)
                retry_idx = 0
                delay = self.settings.rescan_interval_seconds
            elif outcome == "empty":
                self._set_phase(UploadPhase.EMPTY)
                retry_idx = 0
                delay = self.settings.rescan_interval_seconds
            elif outcome == "no_wifi":
                self._set_phase(UploadPhase.NO_WIFI)
                delays = self.settings.retry_delays_seconds
                delay = delays[min(retry_idx, len(delays) - 1)]
                retry_idx += 1
                log.info("Upload retry planned category=no_wifi delay_s=%s", delay)
            elif outcome == "partial":
                self._set_phase(UploadPhase.PARTIAL)
                delays = self.settings.retry_delays_seconds
                delay = delays[min(retry_idx, len(delays) - 1)]
                retry_idx += 1
                log.info(
                    "Upload retry planned category=partial delay_s=%s", delay
                )
            else:
                self._set_phase(UploadPhase.FTP_ERROR)
                delays = self.settings.retry_delays_seconds
                delay = delays[min(retry_idx, len(delays) - 1)]
                retry_idx += 1
                log.info(
                    "Upload retry planned category=ftp_error delay_s=%s", delay
                )

            self._wait(delay)

    def _wait(self, seconds: float) -> None:
        end = self._clock() + max(0.0, seconds)
        while not self._stop.is_set() and self._clock() < end:
            self._sleep(min(0.2, end - self._clock()))

    def _cycle_once(self) -> str:
        wifi = self._wifi_check(self.settings.interface)
        if not wifi.ready:
            log.info(
                "Upload no WiFi detail=%s status=%s",
                wifi.detail,
                wifi.status.value,
            )
            return "no_wifi"

        if not self.settings.password_configured:
            log.error("Upload FTP password missing (set in config or HWSNIFF_FTP_PASSWORD)")
            return "ftp_error"

        self._set_phase(UploadPhase.ACTIVE)
        self._sync_filesystem()
        pending = sorted(
            self.store.pending_or_failed(),
            key=lambda r: (r.mtime, r.remote_name),
        )
        counts = self.store.counts()
        log.info(
            "Upload scan pending=%s failed=%s uploaded=%s total=%s",
            counts.get("pending", 0),
            counts.get("failed", 0),
            counts.get("uploaded", 0),
            sum(counts.values()),
        )

        if not pending:
            return "empty"

        uploaded = 0
        failed = 0
        for rec in pending:
            if self._stop.is_set():
                break
            ok = self._upload_one(rec)
            if ok:
                uploaded += 1
            else:
                failed += 1
            try:
                self.store.save()
            except OSError as exc:
                log.error("upload state save failed: %s", type(exc).__name__)

        log.info(
            "Upload cycle done uploaded=%s failed=%s", uploaded, failed
        )
        if failed and uploaded:
            return "partial"
        if failed:
            return "ftp_error"
        if uploaded:
            return "success"
        return "empty"

    def _sync_filesystem(self) -> None:
        root = Path(self.settings.source_root)
        bundles = list_export_bundles(
            root, suffixes=self.settings.bundle_suffixes
        )
        for path in bundles:
            try:
                st = path.stat()
                digest = sha256_file(path)
            except OSError as exc:
                log.warning(
                    "skip unreadable bundle %s (%s)",
                    path.name,
                    type(exc).__name__,
                )
                continue
            local = str(path.resolve())
            existing = self.store.find_uploaded_match(
                local_path=local, size=st.st_size, sha256=digest
            )
            if existing:
                continue
            # Same path+hash already pending/failed?
            known = [
                r
                for r in self.store.get_by_path(local)
                if r.sha256 == digest and r.size == st.st_size
            ]
            if known:
                continue
            # Unique remote name so content changes do not collide with an older upload
            stem = path.stem
            suffix = path.suffix
            remote_name = f"{stem}_{digest[:12]}{suffix}"
            rec = BundleRecord(
                local_path=local,
                remote_name=remote_name,
                size=st.st_size,
                mtime=st.st_mtime,
                sha256=digest,
                status=BundleStatus.PENDING,
            )
            self.store.upsert(rec)
            log.info("Upload queued file=%s size=%s", path.name, st.st_size)
        try:
            self.store.save()
        except OSError as exc:
            log.error("upload state save failed: %s", type(exc).__name__)

    def _upload_one(self, rec: BundleRecord) -> bool:
        path = Path(rec.local_path)
        if not path.is_file():
            self.store.mark_failed(rec, "local_missing")
            return False

        # Recover rename-before-manifest: remote final already matches size
        remote_size = self.uploader.remote_final_size(rec.remote_name)
        if remote_size is not None and remote_size == rec.size:
            log.info(
                "Upload recover existing remote=%s size=%s",
                rec.remote_name,
                remote_size,
            )
            self.store.mark_uploaded(rec)
            return True
        if remote_size is not None and remote_size != rec.size:
            self.store.mark_failed(
                rec,
                f"remote_collision size={remote_size}",
            )
            log.error(
                "Upload remote collision file=%s category=rename",
                rec.remote_name,
            )
            return False

        self._set_phase(UploadPhase.ACTIVE)
        self.store.mark_uploading(rec)
        log.info(
            "Upload sending file=%s attempt=%s",
            rec.remote_name,
            rec.attempts,
        )
        result = self.uploader.upload_file(path, rec.remote_name)
        if result.ok:
            self.store.mark_uploaded(rec)
            log.info("Upload finished file=%s", rec.remote_name)
            return True

        category = result.category or FtpErrorCategory.UNKNOWN
        self.store.mark_failed(rec, f"{category}:{result.message}")
        log.warning(
            "Upload failed file=%s category=%s",
            rec.remote_name,
            category,
        )
        return False


def _phase_to_pattern(phase: UploadPhase) -> UploadLedPattern:
    return {
        UploadPhase.IDLE: UploadLedPattern.IDLE,
        UploadPhase.ACTIVE: UploadLedPattern.ACTIVE,
        UploadPhase.SUCCESS: UploadLedPattern.SUCCESS,
        UploadPhase.EMPTY: UploadLedPattern.EMPTY,
        UploadPhase.NO_WIFI: UploadLedPattern.NO_WIFI,
        UploadPhase.FTP_ERROR: UploadLedPattern.FTP_ERROR,
        UploadPhase.PARTIAL: UploadLedPattern.PARTIAL,
    }.get(phase, UploadLedPattern.IDLE)
