from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .status import PhaseStatus, classify_exception


@dataclass
class AttemptRecord:
    attempt: int
    status: str
    latency_ms: float
    error: str | None = None


@dataclass
class RetryResult:
    status: PhaseStatus
    value: Any = None
    attempts: list[AttemptRecord] = field(default_factory=list)
    error: str | None = None


def run_with_retry(
    func: Callable[[], Any],
    *,
    retry_count: int = 3,
    retry_delay_ms: float = 150.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException], None] | None = None,
    reselect: Callable[[], None] | None = None,
) -> RetryResult:
    """Run ``func`` with limited retries. Never requires tag removal."""
    attempts = max(1, int(retry_count))
    delay = max(0.0, float(retry_delay_ms) / 1000.0)
    records: list[AttemptRecord] = []
    last_exc: BaseException | None = None

    for i in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            if reselect is not None and i > 1:
                reselect()
            value = func()
            latency = (time.monotonic() - t0) * 1000.0
            records.append(
                AttemptRecord(
                    attempt=i,
                    status=PhaseStatus.OK.value,
                    latency_ms=round(latency, 2),
                )
            )
            return RetryResult(
                status=PhaseStatus.OK, value=value, attempts=records
            )
        except BaseException as exc:  # noqa: BLE001 — phase isolation
            latency = (time.monotonic() - t0) * 1000.0
            last_exc = exc
            status = classify_exception(exc)
            records.append(
                AttemptRecord(
                    attempt=i,
                    status=status.value,
                    latency_ms=round(latency, 2),
                    error=str(exc),
                )
            )
            if on_retry is not None:
                on_retry(i, exc)
            if i >= attempts:
                break
            sleep(delay)

    assert last_exc is not None
    return RetryResult(
        status=classify_exception(last_exc),
        value=None,
        attempts=records,
        error=str(last_exc),
    )
