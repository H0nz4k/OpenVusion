"""Technology-aware read-only capture probe.

AutoCaptureProbe keeps the proven NTAG I2C Plus path intact and adds a
protocol-confirmed FeliCa / NFC Forum Type 3 branch for SOLUM-like targets.

Dispatch rule:
- known/normal NTAG-sized targets -> existing NTAG path;
- 8-byte ID or observed tag_type 0x85 -> try native FeliCa Poll first;
- FeliCa is confirmed only after a successful native Poll whose IDm matches
  the SearchTag identifier;
- if the FeliCa probe is not confirmed, fall back to the original NTAG path.

All FeliCa operations in this module are strictly read-only.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..protocol import SerialCommunicationError
from .capture import CaptureProbe
from .felica import (
    FELICA_NDEF_RO_SERVICE,
    FELICA_NDEF_SYSTEM_CODE,
    FelicaPollResult,
    felica_poll,
    parse_type3_attribute_block,
    request_service_diag,
    request_system_codes,
    select_ndef_and_read_block,
)
from .retry import run_with_retry
from .status import PhaseStatus

TECH_UNKNOWN = "unknown"
TECH_NTAG = "ntag_i2c_plus"
TECH_FELICA = "felica_type3"


class AutoCaptureProbe(CaptureProbe):
    """CaptureProbe with safe automatic NTAG/FeliCa dispatch."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._technology = TECH_UNKNOWN
        self._felica_poll_any: FelicaPollResult | None = None
        self._felica_poll_ndef: FelicaPollResult | None = None
        self._felica_system_codes: list[int] = []
        self._felica_request_service: bool | None = None
        self._felica_attribute: dict[str, Any] | None = None
        self._felica_blocks: dict[int, bytes] = {}
        self._felica_tail_blocks: dict[int, bytes] = {}

    # ------------------------------------------------------------------ dispatch

    def _felica_candidate(self) -> bool:
        # The SOLUM family observed in the field reports tag_type 0x85 and an
        # 8-byte SearchTag ID. Neither signal alone is treated as proof.
        if self._tag_type == 0x85:
            return True
        if self._uid and len(self._uid) == 16:
            return True
        return False

    def _format_tag_type(self) -> str | None:
        if self._tag_type is None:
            return None
        base = f"0x{self._tag_type:02X}"
        if self._technology == TECH_FELICA:
            return f"{base} / FeliCa / NFC Forum Type 3"
        return super()._format_tag_type()

    def _set_technology(self, technology: str, **details: Any) -> None:
        self._technology = technology
        if self._store is not None:
            self._store.update_summary(
                technology=technology,
                technology_dispatch={
                    "technology": technology,
                    "method": details.pop("method", "protocol_probe"),
                    **details,
                },
            )
            self._store.append_event(
                "technology_detected",
                technology=technology,
                **details,
            )
        self._fire_event("technology_detected", technology=technology, **details)
        self._emit(f"Technology: {technology}")

    def _run_identification(self) -> None:
        # Do not disturb the known-good 7-byte NTAG path with unnecessary
        # FeliCa commands. For SOLUM-like/8-byte targets, native Poll is the
        # discriminator; tag_type 0x85 alone is never enough.
        if self._felica_candidate():
            confirmed = self._try_felica_identification()
            if confirmed:
                return

        super()._run_identification()
        if self._ntag_capable:
            self._set_technology(TECH_NTAG, method="ntag_get_version")
        else:
            self._set_technology(TECH_UNKNOWN, method="fallback_identification")

    def _try_felica_identification(self) -> bool:
        store = self._store
        assert store is not None and self._client is not None and self._uid is not None
        expected_idm = bytes.fromhex(self._uid)
        if len(expected_idm) != 8:
            return False

        # A failed native Poll simply means "not confirmed as FeliCa" and we
        # fall back to the original NTAG identification path.
        try:
            poll_any = felica_poll(self._client, 0xFFFF)
        except Exception as exc:  # noqa: BLE001 - discriminator must fail soft
            store.append_event("felica_probe_not_confirmed", error=str(exc))
            return False

        # Once native FeliCa answered, an IDm mismatch is a target-change
        # safety event, not a reason to try a different protocol on that tag.
        if poll_any.idm != expected_idm:
            raise SerialCommunicationError(
                "FeliCa Poll IDm does not match locked SearchTag ID: "
                f"{self._uid} -> {poll_any.idm.hex().upper()}"
            )

        self._felica_poll_any = poll_any
        self._set_technology(
            TECH_FELICA,
            method="felica_poll",
            idm=poll_any.idm.hex().upper(),
            pmm=poll_any.pmm.hex().upper(),
        )

        data: dict[str, Any] = {
            "technology": TECH_FELICA,
            "confirmed": True,
            "confirmation": "native_felica_poll_idm_match",
            "searchtag_id": self._uid,
            "poll_ffff": poll_any.to_dict(),
        }
        status = PhaseStatus.OK

        try:
            self._felica_system_codes = request_system_codes(self._client)
            data["system_codes"] = [
                f"0x{code:04X}" for code in self._felica_system_codes
            ]
        except Exception as exc:  # noqa: BLE001 - FeliCa already confirmed
            self._felica_system_codes = []
            data["system_codes_error"] = f"{type(exc).__name__}: {exc}"
            status = PhaseStatus.PARTIAL

        # Prefer RequestSystemCode, but do not hard-gate NDEF on it alone —
        # a flaky/empty 1D03 response must not skip a working Poll(0x12FC).
        ndef_listed = FELICA_NDEF_SYSTEM_CODE in self._felica_system_codes
        data["ndef_system"] = {
            "system_code": "0x12FC",
            "available": ndef_listed,
            "listed_by_request_system_code": ndef_listed,
        }
        try_ndef = ndef_listed
        if not try_ndef:
            try:
                probe = felica_poll(self._client, FELICA_NDEF_SYSTEM_CODE)
                if probe.idm != expected_idm:
                    raise SerialCommunicationError(
                        "FeliCa Poll(0x12FC) changed IDm: "
                        f"{self._uid} -> {probe.idm.hex().upper()}"
                    )
                try_ndef = True
                self._felica_poll_ndef = probe
                data["poll_12fc"] = probe.to_dict()
                data["ndef_system"]["available"] = True
                data["ndef_system"]["discovered_via"] = "direct_poll_fallback"
            except SerialCommunicationError:
                raise
            except Exception as exc:  # noqa: BLE001 - soft: keep FeliCa confirmed
                data["ndef_system"]["poll_error"] = f"{type(exc).__name__}: {exc}"
                status = PhaseStatus.PARTIAL

        if try_ndef:
            if self._felica_poll_ndef is None:
                selected = felica_poll(self._client, FELICA_NDEF_SYSTEM_CODE)
                if selected.idm != expected_idm:
                    raise SerialCommunicationError(
                        "FeliCa Poll(0x12FC) changed IDm: "
                        f"{self._uid} -> {selected.idm.hex().upper()}"
                    )
                self._felica_poll_ndef = selected
                data["poll_12fc"] = selected.to_dict()

            # Diagnostic only: physical SOLUM returned Result=false here while
            # direct CHECK succeeded. Never gate the read on this result.
            try:
                self._felica_request_service = request_service_diag(
                    self._client, FELICA_NDEF_RO_SERVICE
                )
                data["request_service_000b"] = {
                    "result": self._felica_request_service,
                    "diagnostic_only": True,
                }
            except Exception as exc:  # noqa: BLE001
                data["request_service_000b"] = {
                    "result": None,
                    "diagnostic_only": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            try:
                block0 = select_ndef_and_read_block(self._client, expected_idm, 0)
                attr = parse_type3_attribute_block(block0.data)
                self._felica_blocks[0] = block0.data
                self._felica_attribute = attr
                data["block0_check"] = block0.to_dict()
                data["attribute_block"] = attr
                if not attr.get("valid_checksum"):
                    status = PhaseStatus.PARTIAL
            except Exception as exc:  # noqa: BLE001 - technology still confirmed
                data["block0_error"] = f"{type(exc).__name__}: {exc}"
                status = PhaseStatus.PARTIAL
        else:
            status = PhaseStatus.PARTIAL

        store.write_phase("identification", data, status.value)
        store.update_summary(
            tag_type=self._format_tag_type(),
            technology=TECH_FELICA,
            identification=data,
            felica={
                "confirmed": True,
                "idm": poll_any.idm.hex().upper(),
                "pmm": poll_any.pmm.hex().upper(),
                "system_codes": [
                    f"0x{code:04X}" for code in self._felica_system_codes
                ],
                "attribute_block": self._felica_attribute,
            },
        )
        self._phase_banner("Identification", f".... {status.value.upper()} (FeliCa)")
        self._phase_end("identification", status.value)
        return True

    # ------------------------------------------------------------------ FeliCa memory

    def _felica_expected_idm(self) -> bytes:
        if self._uid is None:
            raise RuntimeError("No locked UID")
        raw = bytes.fromhex(self._uid)
        if len(raw) != 8:
            raise RuntimeError("Locked UID is not an 8-byte FeliCa IDm")
        return raw

    def _read_felica_block_with_retry(self, block_no: int):
        expected_idm = self._felica_expected_idm()

        def op():
            return select_ndef_and_read_block(
                self._client,
                expected_idm,
                block_no,
            )

        return run_with_retry(
            op,
            retry_count=self.config.retry_count,
            retry_delay_ms=self.config.retry_delay_ms,
            sleep=self._sleep,
        )

    def _run_eeprom(self) -> None:
        if self._technology != TECH_FELICA:
            super()._run_eeprom()
            return

        store = self._store
        assert store is not None and self._client is not None

        # Public dump is gated on a successful NDEF select + Attribute Block,
        # not on RequestSystemCode listing alone (empty 1D03 still allows Poll 0x12FC).
        if self._felica_poll_ndef is None or not self._felica_attribute:
            store.write_phase(
                "eeprom",
                {
                    "technology": TECH_FELICA,
                    "reason": "NFC Forum Type 3 public NDEF area not available",
                    "poll_12fc": self._felica_poll_ndef.to_dict()
                    if self._felica_poll_ndef
                    else None,
                    "attribute_present": bool(self._felica_attribute),
                },
                PhaseStatus.UNSUPPORTED.value,
            )
            self._phase_banner("FeliCa public .....", "UNSUPPORTED")
            self._phase_end("eeprom", PhaseStatus.UNSUPPORTED.value)
            return

        nmaxb = int(self._felica_attribute.get("nmaxb") or 0)
        total = nmaxb + 1  # block 0 Attribute + blocks 1..Nmaxb
        ok = 0
        attempts_out: list[dict[str, Any]] = []
        nonzero: dict[str, str] = {}

        for block_no in range(0, total):
            if self._stopping():
                self._aborted = True
                break
            self._fire_event(
                "phase_progress",
                phase="eeprom",
                current=block_no + 1,
                total=total,
            )
            result = self._read_felica_block_with_retry(block_no)
            attempts = self._attempts_payload(result.attempts)
            attempts_out.append(
                {
                    "block": block_no,
                    "status": result.status.value,
                    "attempts": attempts,
                    "error": result.error,
                }
            )
            if result.status == PhaseStatus.OK and result.value is not None:
                data = result.value.data
                self._felica_blocks[block_no] = data
                ok += 1
                if any(data) and block_no != 0:
                    nonzero[str(block_no)] = data.hex().upper()
            else:
                store.add_error(
                    phase="eeprom",
                    code=result.status.value,
                    message=result.error or f"FeliCa block {block_no} read failed",
                    details={"block": block_no},
                )

            current_status = (
                PhaseStatus.OK
                if ok == block_no + 1
                else PhaseStatus.PARTIAL
                if ok
                else result.status
            )
            store.write_phase(
                "eeprom",
                {
                    "technology": TECH_FELICA,
                    "mode": "felica_type3_public",
                    "system_code": "0x12FC",
                    "service_code": "0x000B",
                    "block_size": 16,
                    "nmaxb": nmaxb,
                    "blocks_ok": ok,
                    "blocks_total": block_no + 1,
                    "nonzero_blocks": nonzero,
                    "blocks": {
                        str(k): v.hex().upper()
                        for k, v in sorted(self._felica_blocks.items())
                    },
                    "block_attempts": attempts_out,
                },
                current_status.value,
            )

        if ok == total:
            status = PhaseStatus.OK
        elif ok:
            status = PhaseStatus.PARTIAL
        else:
            status = PhaseStatus.READER_ERROR

        # Preserve the exact physically readable Type-3 area as a binary
        # artifact only when every block was acquired in order.
        if status == PhaseStatus.OK:
            raw = b"".join(self._felica_blocks[i] for i in range(total))
            path = store.root / "felica_public.bin"
            path.write_bytes(raw)
            store._track(path)  # noqa: SLF001 - same internal persistence layer

        store.write_phase(
            "eeprom",
            {
                "technology": TECH_FELICA,
                "mode": "felica_type3_public",
                "system_code": "0x12FC",
                "service_code": "0x000B",
                "block_size": 16,
                "nmaxb": nmaxb,
                "blocks_ok": ok,
                "blocks_total": total,
                "active_ndef_length": int(
                    self._felica_attribute.get("ndef_length") or 0
                ),
                "nonzero_blocks": nonzero,
                "blocks": {
                    str(k): v.hex().upper()
                    for k, v in sorted(self._felica_blocks.items())
                },
                "block_attempts": attempts_out,
            },
            status.value,
        )
        store.update_summary(
            felica_public={
                "blocks_ok": ok,
                "blocks_total": total,
                "nmaxb": nmaxb,
                "active_ndef_length": int(
                    self._felica_attribute.get("ndef_length") or 0
                ),
                "nonzero_blocks": nonzero,
            }
        )
        self._phase_banner(
            "FeliCa public .....",
            f"{status.value.upper()}, {ok}/{total} blocks",
        )
        self._phase_end("eeprom", status.value)

    def _run_application(self) -> None:
        if self._technology != TECH_FELICA:
            super()._run_application()
            return

        store = self._store
        assert store is not None
        attr = self._felica_attribute or {}
        nmaxb = int(attr.get("nmaxb") or 0)

        # The physical SOLUM sample stores stable vendor metadata in 54..56.
        # Capture those blocks even when a full public dump was disabled.
        tail_numbers = [b for b in (54, 55, 56) if b <= nmaxb]
        errors: list[dict[str, Any]] = []
        for block_no in tail_numbers:
            if block_no in self._felica_blocks:
                self._felica_tail_blocks[block_no] = self._felica_blocks[block_no]
                continue
            result = self._read_felica_block_with_retry(block_no)
            if result.status == PhaseStatus.OK and result.value is not None:
                self._felica_blocks[block_no] = result.value.data
                self._felica_tail_blocks[block_no] = result.value.data
            else:
                errors.append(
                    {
                        "block": block_no,
                        "status": result.status.value,
                        "error": result.error,
                    }
                )

        if not self._felica_tail_blocks:
            # A non-SOLUM FeliCa Type-3 target may have a smaller public area.
            status = PhaseStatus.OK if self._felica_attribute else PhaseStatus.PARTIAL
        else:
            status = PhaseStatus.OK if not errors else PhaseStatus.PARTIAL

        ordered = b"".join(
            self._felica_tail_blocks[b]
            for b in sorted(self._felica_tail_blocks)
        )
        data: dict[str, Any] = {
            "technology": TECH_FELICA,
            "mode": "felica_type3_metadata",
            "active_ndef_length": int(attr.get("ndef_length") or 0),
            "attribute_block": attr,
            "tail_blocks": {
                str(k): v.hex().upper()
                for k, v in sorted(self._felica_tail_blocks.items())
            },
            "raw_hex": ordered.hex().upper(),
            "errors": errors,
        }

        if 54 in self._felica_tail_blocks and 55 in self._felica_tail_blocks:
            b54 = self._felica_tail_blocks[54]
            b55 = self._felica_tail_blocks[55]
            # Research-only candidates discovered on the physical SOLUM sample.
            # Labels deliberately remain hypotheses until cross-tag/RF correlation.
            data["research_candidates"] = {
                "boundary_6byte_hex": (b54[-3:] + b55[:3]).hex().upper(),
                "block54_bytes_8_11_hex": b54[8:12].hex().upper(),
                "block54_bytes_8_11_le_u32": int.from_bytes(b54[8:12], "little"),
                "confidence": "hypothesis",
            }

        store.write_phase("application", data, status.value)
        store.update_summary(felica_metadata=data)
        self._phase_banner("FeliCa metadata ...", status.value.upper())
        self._phase_end("application", status.value)

    def _run_session(self) -> None:
        if self._technology != TECH_FELICA:
            super()._run_session()
            return
        # There is no NTAG I2C session-register equivalent in this Type-3
        # capture. Marking SKIPPED keeps a complete FeliCa capture SUCCESS.
        self._skip_phase(
            "session",
            "FeliCa Type 3 selected; NTAG session-register phase not applicable",
        )

    def _run_verification(self) -> None:
        if self._technology != TECH_FELICA:
            super()._run_verification()
            return

        store = self._store
        assert store is not None and self._client is not None
        expected_idm = self._felica_expected_idm()
        checks: dict[str, Any] = {
            "technology": TECH_FELICA,
            "system_code": "0x12FC",
        }
        status = PhaseStatus.OK

        try:
            selected = felica_poll(self._client, FELICA_NDEF_SYSTEM_CODE)
            same_idm = selected.idm == expected_idm
            checks["poll_12fc"] = {
                **selected.to_dict(),
                "idm_match": same_idm,
            }
            if not same_idm:
                raise SerialCommunicationError("Verification Poll changed IDm")
        except Exception as exc:  # noqa: BLE001
            checks["poll_error"] = f"{type(exc).__name__}: {exc}"
            status = PhaseStatus.READER_ERROR

        verify_blocks = [0] + [
            b for b in (54, 55, 56) if b in self._felica_blocks
        ]
        block_checks: dict[str, Any] = {}
        if status == PhaseStatus.OK:
            for block_no in verify_blocks:
                result = self._read_felica_block_with_retry(block_no)
                if result.status == PhaseStatus.OK and result.value is not None:
                    expected = self._felica_blocks.get(block_no)
                    same = expected is None or result.value.data == expected
                    block_checks[str(block_no)] = {
                        "status": "ok" if same else "changed",
                        "data_hex": result.value.data.hex().upper(),
                        "matches_capture": same,
                    }
                    if not same:
                        status = PhaseStatus.PARTIAL
                else:
                    block_checks[str(block_no)] = {
                        "status": result.status.value,
                        "error": result.error,
                    }
                    status = PhaseStatus.PARTIAL
        checks["blocks"] = block_checks

        store.write_phase("verification", checks, status.value)
        self._phase_banner("Verification ......", f"{status.value.upper()} (FeliCa)")
        self._phase_end("verification", status.value)
