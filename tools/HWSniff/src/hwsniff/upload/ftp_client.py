"""FTP / FTPS upload helper (stdlib ftplib). Never logs passwords."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from ftplib import FTP, FTP_TLS, error_perm, error_temp
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import UploadSettings

log = logging.getLogger(__name__)


class FtpErrorCategory(str):
    DNS_CONNECT = "dns_connect"
    TLS = "tls"
    AUTH = "auth"
    REMOTE_DIR = "remote_dir"
    TRANSFER = "transfer"
    RENAME = "rename"
    LOCAL = "local"
    UNKNOWN = "unknown"


@dataclass
class FtpResult:
    ok: bool
    category: str = FtpErrorCategory.UNKNOWN
    message: str = ""
    remote_size: int | None = None


class FtpSession(Protocol):
    def connect(self, host: str, port: int = 21, timeout: float = 15) -> str: ...

    def login(self, user: str = "", passwd: str = "") -> str: ...

    def set_pasv(self, val: bool) -> None: ...

    def cwd(self, dirname: str) -> str: ...

    def storbinary(self, cmd: str, fp: Any, blocksize: int = 8192) -> str: ...

    def rename(self, fromname: str, toname: str) -> str: ...

    def size(self, filename: str) -> int | None: ...

    def delete(self, filename: str) -> str: ...

    def quit(self) -> str: ...

    def close(self) -> None: ...


FtpFactory = Callable[[], Any]


def _sanitize(msg: str) -> str:
    text = str(msg)
    if "://" in text and "@" in text:
        return "connection_error"
    return text[:300]


class BundleUploader:
    def __init__(
        self,
        settings: UploadSettings,
        *,
        ftp_factory: FtpFactory | None = None,
    ) -> None:
        self.settings = settings
        self._ftp_factory = ftp_factory

    def _make_ftp(self) -> Any:
        if self._ftp_factory is not None:
            return self._ftp_factory()
        if self.settings.use_tls:
            return FTP_TLS()
        return FTP()

    def remote_final_size(self, remote_name: str) -> int | None:
        """Return size of final remote file if present, else None."""
        ftp = None
        try:
            ftp = self._connect_login()
            try:
                size = ftp.size(remote_name)
            except (error_perm, error_temp, OSError, AttributeError):
                return None
            return int(size) if size is not None else None
        except Exception as exc:  # noqa: BLE001
            log.warning("remote size check failed category=%s", _classify(exc))
            return None
        finally:
            _close_quiet(ftp)

    def upload_file(self, local_path: Path, remote_name: str) -> FtpResult:
        settings = self.settings
        part_name = f"{remote_name}.part"
        ftp = None
        try:
            ftp = self._connect_login()
            try:
                ftp.cwd(settings.remote_dir)
            except Exception as exc:  # noqa: BLE001
                return FtpResult(
                    False, FtpErrorCategory.REMOTE_DIR, _sanitize(str(exc))
                )

            # Clean leftover part if any
            try:
                ftp.delete(part_name)
            except Exception:  # noqa: BLE001
                pass

            with local_path.open("rb") as handle:
                ftp.storbinary(f"STOR {part_name}", handle)

            try:
                ftp.rename(part_name, remote_name)
            except Exception as exc:  # noqa: BLE001
                # Leave .part for next attempt; do not claim success
                return FtpResult(
                    False, FtpErrorCategory.RENAME, _sanitize(str(exc))
                )

            remote_size: int | None = None
            try:
                remote_size = ftp.size(remote_name)
            except Exception:  # noqa: BLE001
                remote_size = None

            local_size = local_path.stat().st_size
            if remote_size is not None and int(remote_size) != local_size:
                return FtpResult(
                    False,
                    FtpErrorCategory.TRANSFER,
                    f"size_mismatch local={local_size} remote={remote_size}",
                    remote_size=int(remote_size),
                )

            log.info(
                "FTP upload ok remote=%s bytes=%s",
                remote_name,
                local_size,
            )
            return FtpResult(True, message="ok", remote_size=local_size)
        except Exception as exc:  # noqa: BLE001
            category = _classify(exc)
            return FtpResult(False, category, _sanitize(str(exc)))
        finally:
            _close_quiet(ftp)

    def _connect_login(self) -> Any:
        settings = self.settings
        ftp = self._make_ftp()
        try:
            ftp.connect(
                settings.server,
                settings.port,
                timeout=settings.connect_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            _close_quiet(ftp)
            raise ConnectionError(f"connect:{_sanitize(str(exc))}") from exc

        if settings.use_tls and hasattr(ftp, "auth"):
            try:
                ftp.auth()
                if hasattr(ftp, "prot_p"):
                    ftp.prot_p()
            except Exception as exc:  # noqa: BLE001
                _close_quiet(ftp)
                raise OSError(f"tls:{_sanitize(str(exc))}") from exc

        try:
            ftp.login(settings.username, settings.password)
        except error_perm as exc:
            _close_quiet(ftp)
            raise PermissionError(f"auth:{_sanitize(str(exc))}") from exc
        except Exception as exc:  # noqa: BLE001
            _close_quiet(ftp)
            raise PermissionError(f"auth:{_sanitize(str(exc))}") from exc

        ftp.set_pasv(settings.passive)
        return ftp


def _classify(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if isinstance(exc, PermissionError) or "auth" in msg or "530" in msg:
        return FtpErrorCategory.AUTH
    if "tls" in msg or "ssl" in msg or "certificate" in msg:
        return FtpErrorCategory.TLS
    if isinstance(exc, ConnectionError) or "connect" in msg or "gaierror" in name:
        return FtpErrorCategory.DNS_CONNECT
    if "rename" in msg:
        return FtpErrorCategory.RENAME
    if "cwd" in msg or "550" in msg:
        return FtpErrorCategory.REMOTE_DIR
    return FtpErrorCategory.UNKNOWN


def _close_quiet(ftp: Any) -> None:
    if ftp is None:
        return
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass
