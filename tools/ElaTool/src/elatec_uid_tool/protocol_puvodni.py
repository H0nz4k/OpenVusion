from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # Umožní používat offline analyzátor i bez pyserial.
    serial = None
    list_ports = None


PROTOCOL_ERRORS = {
    0: "ERR_NONE",
    1: "ERR_UNKNOWN_FUNCTION",
    2: "ERR_MISSING_PARAMETER",
    3: "ERR_UNUSED_PARAMETERS",
    4: "ERR_INVALID_FUNCTION",
    5: "ERR_PARSER",
}


class ElatecError(RuntimeError):
    pass


class SerialDependencyError(ElatecError):
    pass


class SerialCommunicationError(ElatecError):
    pass


class ProtocolError(ElatecError):
    def __init__(self, code: int):
        self.code = code
        name = PROTOCOL_ERRORS.get(code, f"ERR_{code}")
        super().__init__(f"Simple Protocol vrátil chybu {code}: {name}")


@dataclass(frozen=True)
class ReaderInfo:
    port: str
    version: str
    device_type: int
    lf_supported_mask: int
    hf_supported_mask: int


@dataclass(frozen=True)
class TagRead:
    tag_type: int
    id_bit_count: int
    id_bytes: bytes

    @property
    def id_hex(self) -> str:
        return self.id_bytes.hex().upper()


def require_pyserial() -> None:
    if serial is None or list_ports is None:
        raise SerialDependencyError(
            "Chybí balíček pyserial. Nainstaluj jej příkazem: "
            "python -m pip install pyserial"
        )


def enumerate_ports() -> list[tuple[str, str, str]]:
    require_pyserial()
    result: list[tuple[str, str, str]] = []
    for item in list_ports.comports():
        result.append((item.device, item.description or "", item.hwid or ""))
    return result


class SerialAsciiTransport:
    """Simple Protocol: ASCII, CRC off, příkazy a odpovědi ukončené CR."""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 1.2,
    ) -> None:
        require_pyserial()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            time.sleep(0.20)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except Exception as exc:
            raise SerialCommunicationError(
                f"Nelze otevřít {self.port}: {exc}. "
                "Zkontroluj, zda port nepoužívá AppBlaster nebo terminál."
            ) from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "SerialAsciiTransport":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def exchange(self, command: bytes) -> bytes:
        if self._serial is None:
            raise SerialCommunicationError("Sériový port není otevřený.")

        wire = command.hex().upper().encode("ascii") + b"\r"
        try:
            self._serial.reset_input_buffer()
            self._serial.write(wire)
            self._serial.flush()

            deadline = time.monotonic() + self.timeout
            line = b""
            while time.monotonic() < deadline:
                chunk = self._serial.read_until(b"\r")
                if chunk:
                    line += chunk
                    if b"\r" in line:
                        break

            cleaned = line.strip(b"\r\n\t ")
            if not cleaned:
                raise SerialCommunicationError(
                    f"{self.port} neodpověděl na příkaz {command.hex().upper()}. "
                    "Je v čtečce nahraný PRS Simple Protocol firmware?"
                )

            try:
                text = cleaned.decode("ascii")
            except UnicodeDecodeError as exc:
                raise SerialCommunicationError(
                    f"Neplatná ne-ASCII odpověď: {cleaned!r}"
                ) from exc

            if not re.fullmatch(r"[0-9A-Fa-f]+", text) or len(text) % 2:
                raise SerialCommunicationError(
                    f"Neplatná hex odpověď Simple Protocol: {text!r}"
                )

            return bytes.fromhex(text)
        except ElatecError:
            raise
        except Exception as exc:
            raise SerialCommunicationError(
                f"Chyba komunikace na {self.port}: {exc}"
            ) from exc


class SimpleProtocolClient:
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 1.2,
    ) -> None:
        self.transport = SerialAsciiTransport(port, baudrate, timeout)
        self.port = port

    def __enter__(self) -> "SimpleProtocolClient":
        self.transport.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.transport.close()

    def _request(self, command: bytes) -> bytes:
        response = self.transport.exchange(command)
        if not response:
            raise SerialCommunicationError("Čtečka vrátila prázdnou odpověď.")
        status = response[0]
        if status != 0:
            raise ProtocolError(status)
        return response[1:]

    def get_version_string(self, max_len: int = 0xFF) -> str:
        payload = self._request(b"\x00\x04" + bytes([max_len]))
        if not payload:
            return ""
        length = payload[0]
        data = payload[1 : 1 + length]
        if len(data) != length:
            raise SerialCommunicationError(
                "Neúplná odpověď GetVersionString."
            )
        return data.decode("ascii", errors="replace")

    def get_device_type(self) -> int:
        payload = self._request(b"\x00\x06")
        if len(payload) != 1:
            raise SerialCommunicationError(
                f"Neočekávaná délka GetDeviceType: {len(payload)}"
            )
        return payload[0]

    def get_supported_tag_types(self) -> tuple[int, int]:
        payload = self._request(b"\x05\x04")
        if len(payload) != 8:
            raise SerialCommunicationError(
                f"Neočekávaná délka GetSupportedTagTypes: {len(payload)}"
            )
        lf_mask = int.from_bytes(payload[0:4], "little")
        hf_mask = int.from_bytes(payload[4:8], "little")
        return lf_mask, hf_mask

    def get_active_tag_types(self) -> tuple[int, int]:
        payload = self._request(b"\x05\x03")
        if len(payload) != 8:
            raise SerialCommunicationError(
                f"Neočekávaná délka GetTagTypes: {len(payload)}"
            )
        return (
            int.from_bytes(payload[0:4], "little"),
            int.from_bytes(payload[4:8], "little"),
        )

    def set_tag_types(self, lf_mask: int, hf_mask: int) -> None:
        command = (
            b"\x05\x02"
            + lf_mask.to_bytes(4, "little")
            + hf_mask.to_bytes(4, "little")
        )
        payload = self._request(command)
        if payload:
            raise SerialCommunicationError(
                f"SetTagTypes vrátil neočekávaná data: {payload.hex().upper()}"
            )

    def search_tag(self, max_id_bytes: int = 32) -> Optional[TagRead]:
        if not 1 <= max_id_bytes <= 255:
            raise ValueError("max_id_bytes musí být 1 až 255.")
        payload = self._request(b"\x05\x00" + bytes([max_id_bytes]))
        if not payload:
            raise SerialCommunicationError("SearchTag nevrátil hodnotu Result.")
        found = payload[0]
        if found == 0:
            return None
        if found != 1:
            raise SerialCommunicationError(
                f"SearchTag vrátil neplatný Bool: {found}"
            )
        if len(payload) < 3:
            raise SerialCommunicationError("Neúplná odpověď SearchTag.")

        tag_type = payload[1]
        bit_count = payload[2]
        expected_byte_count = math.ceil(bit_count / 8)

        # Byte Array(Var) je v Simple Protocolu prefixované jedním bajtem
        # délky. Např. ID 3D00C000D4 je na drátu jako
        # 05 3D 00 C0 00 D4. Původní parser omylem zahrnoval 05 do UID
        # a zahazoval poslední bajt.
        if len(payload) < 4:
            raise SerialCommunicationError(
                "SearchTag nevrátil délku proměnného pole ID."
            )
        encoded_byte_count = payload[3]
        id_start = 4
        id_end = id_start + encoded_byte_count
        id_bytes = payload[id_start:id_end]

        if len(id_bytes) != encoded_byte_count:
            raise SerialCommunicationError(
                f"SearchTag: deklarováno {encoded_byte_count} ID bajtů, "
                f"přišlo {len(id_bytes)}."
            )
        if encoded_byte_count != expected_byte_count:
            raise SerialCommunicationError(
                f"SearchTag: IDBitCount={bit_count} vyžaduje "
                f"{expected_byte_count} bajtů, odpověď ale deklaruje "
                f"{encoded_byte_count}."
            )
        if len(payload) != id_end:
            raise SerialCommunicationError(
                f"SearchTag vrátil za ID neočekávaná data: "
                f"{payload[id_end:].hex().upper()}"
            )
        return TagRead(tag_type, bit_count, id_bytes)

    def set_rf_off(self) -> None:
        payload = self._request(b"\x05\x01")
        if payload:
            raise SerialCommunicationError(
                f"SetRFOff vrátil neočekávaná data: {payload.hex().upper()}"
            )

    def read_info(self) -> ReaderInfo:
        version = self.get_version_string()
        device_type = self.get_device_type()
        lf_mask, hf_mask = self.get_supported_tag_types()
        return ReaderInfo(
            port=self.port,
            version=version,
            device_type=device_type,
            lf_supported_mask=lf_mask,
            hf_supported_mask=hf_mask,
        )


def parse_search_tag_response(response: bytes) -> Optional[TagRead]:
    """Pomocná čistá funkce pro testy. Vstup obsahuje i status byte."""
    if not response:
        raise SerialCommunicationError("Prázdná odpověď.")
    if response[0] != 0:
        raise ProtocolError(response[0])
    payload = response[1:]
    if not payload or payload[0] == 0:
        return None
    if len(payload) < 4:
        raise SerialCommunicationError("Neúplná SearchTag odpověď.")

    bit_count = payload[2]
    expected_byte_count = math.ceil(bit_count / 8)
    encoded_byte_count = payload[3]
    id_start = 4
    id_end = id_start + encoded_byte_count
    id_bytes = payload[id_start:id_end]

    if len(id_bytes) != encoded_byte_count:
        raise SerialCommunicationError("Neúplné ID.")
    if encoded_byte_count != expected_byte_count:
        raise SerialCommunicationError(
            "Délka Byte Array(Var) neodpovídá IDBitCount."
        )
    if len(payload) != id_end:
        raise SerialCommunicationError("Neočekávaná data za ID.")
    return TagRead(payload[1], bit_count, id_bytes)
