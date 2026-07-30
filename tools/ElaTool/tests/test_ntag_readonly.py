import unittest

from elatec_uid_tool.ntag import (
    SRAM_RF_END_PAGE,
    SRAM_RF_START_PAGE,
    SRAM_SIZE_BYTES,
    NtagI2CPlus,
    crc_a,
)
from elatec_uid_tool.protocol import SerialCommunicationError


class FakeClient:
    def __init__(self, responses: list[bytes | None]):
        self.responses = list(responses)
        self.tx_frames: list[bytes] = []

    def iso14443_3_tdx(self, tx, max_rx_bytes=0xFF, timeout_ms=255):
        self.tx_frames.append(tx)
        if not self.responses:
            raise AssertionError("Neočekávaný RF požadavek")
        return self.responses.pop(0)


def with_crc(data: bytes) -> bytes:
    return data + crc_a(data)


class NtagReadonlyTests(unittest.TestCase):
    def test_fast_read_session(self):
        payload = bytes.fromhex("19 00 F8 48 08 01 01 00")
        client = FakeClient([with_crc(payload)])
        ntag = NtagI2CPlus(client)

        data = ntag.read_session_registers()

        self.assertEqual(data, payload)
        self.assertEqual(client.tx_frames[0][:3], bytes.fromhex("3A EC ED"))

    def test_read_sram_uses_f0_ff(self):
        payload = bytes([i & 0xFF for i in range(SRAM_SIZE_BYTES)])
        client = FakeClient([with_crc(payload)])
        ntag = NtagI2CPlus(client)

        data = ntag.read_sram()

        self.assertEqual(len(data), 64)
        self.assertEqual(data, payload)
        self.assertEqual(
            client.tx_frames[0][:3],
            bytes((0x3A, SRAM_RF_START_PAGE, SRAM_RF_END_PAGE)),
        )

    def test_type2_nak_is_raised(self):
        client = FakeClient([bytes([0x03])])
        ntag = NtagI2CPlus(client)

        with self.assertRaises(SerialCommunicationError) as ctx:
            ntag.read_sram()

        self.assertIn("invalid address", str(ctx.exception).lower())

    def test_short_response_rejected(self):
        client = FakeClient([bytes([0x01, 0x02])])
        ntag = NtagI2CPlus(client)
        with self.assertRaises(SerialCommunicationError):
            ntag.transceive(b"\x60")

    def test_no_write_commands_in_helpers(self):
        # Guardrail: readonly helpers must only issue 0x3A / 0x30 / 0x60 opcodes.
        client = FakeClient(
            [
                with_crc(bytes(8)),
                with_crc(bytes(64)),
                with_crc(bytes(16)),
            ]
        )
        ntag = NtagI2CPlus(client)
        ntag.read_session_registers()
        ntag.read_sram()
        ntag.read_block(0xE8)
        opcodes = {frame[0] for frame in client.tx_frames}
        self.assertTrue(opcodes.issubset({0x3A, 0x30, 0x60}))


if __name__ == "__main__":
    unittest.main()
