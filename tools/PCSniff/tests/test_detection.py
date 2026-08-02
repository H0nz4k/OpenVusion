from __future__ import annotations

import unittest

import _pathsetup  # noqa: F401
from twn4_capture_probe.detection import ReaderSelectionError, resolve_reader_port


class FakePort:
    def __init__(
        self,
        device,
        description="",
        hwid="",
        vid=None,
        pid=None,
        manufacturer=None,
        product=None,
        serial_number=None,
    ):
        self.device = device
        self.description = description
        self.hwid = hwid
        self.vid = vid
        self.pid = pid
        self.manufacturer = manufacturer
        self.product = product
        self.serial_number = serial_number


class FakeClient:
    def __init__(self, port, timeout=2.0):
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def search_tag(self, max_id_bytes=32):
        return None


class DetectionTests(unittest.TestCase):
    def test_auto_detect_single_elatec(self):
        ports = [
            FakePort(
                "COM5",
                description="ELATEC TWN4",
                hwid="USB VID:PID=09D8:0410",
                vid=0x09D8,
                pid=0x0410,
                manufacturer="ELATEC",
                product="TWN4",
            ),
            FakePort("COM1", description="Communications Port"),
        ]
        selected = resolve_reader_port(
            auto_port=True,
            list_ports=lambda: ports,
            client_factory=FakeClient,
            verify=True,
        )
        self.assertEqual(selected.device, "COM5")
        self.assertTrue(selected.verified)

    def test_multiple_elatec_requires_port(self):
        ports = [
            FakePort(
                "COM5",
                description="ELATEC TWN4",
                hwid="USB VID:PID=09D8:0410",
                vid=0x09D8,
                manufacturer="ELATEC",
                product="TWN4",
            ),
            FakePort(
                "COM6",
                description="ELATEC TWN4",
                hwid="USB VID:PID=09D8:0410",
                vid=0x09D8,
                manufacturer="ELATEC",
                product="TWN4",
            ),
        ]
        with self.assertRaises(ReaderSelectionError) as ctx:
            resolve_reader_port(
                auto_port=True,
                list_ports=lambda: ports,
                client_factory=FakeClient,
                verify=True,
            )
        msg = str(ctx.exception)
        self.assertIn("více ELATEC", msg)
        self.assertIn("COM5", msg)
        self.assertIn("COM6", msg)

    def test_no_reader_lists_ports(self):
        ports = [FakePort("COM1", description="Communications Port")]
        with self.assertRaises(ReaderSelectionError) as ctx:
            resolve_reader_port(
                auto_port=True,
                list_ports=lambda: ports,
                client_factory=FakeClient,
                verify=True,
            )
        msg = str(ctx.exception)
        self.assertIn("Nebyla nalezena ELATEC", msg)
        self.assertIn("COM1", msg)


if __name__ == "__main__":
    unittest.main()
