import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from elatec_uid_tool.cli import build_parser, print_matches, select_port_interactively


class WorkflowTests(unittest.TestCase):
    def test_menu_commands_exist(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["test-medium"]).port, "auto")
        self.assertEqual(parser.parse_args(["update-reader"]).devpack, "files520")

    def test_single_reader_is_automatic(self):
        ports = [("COM13", "Serial RFID Device", "USB VID:PID=09D8:0420")]
        with patch("elatec_uid_tool.cli.enumerate_ports", return_value=ports), patch(
            "builtins.input", side_effect=AssertionError("input neměl být volán")
        ):
            self.assertEqual(select_port_interactively(), "COM13")

    def test_default_output_hides_alternatives(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_matches("3D00C000D4", 40, "12583124", "decimal", 50, False)
        text = output.getvalue()
        self.assertIn("First Bit:          8", text)
        self.assertIn("Number of Bits:     32", text)
        self.assertIn("Alternativy jsou skryté", text)
        self.assertNotIn("#2  skóre", text)


if __name__ == "__main__":
    unittest.main()
