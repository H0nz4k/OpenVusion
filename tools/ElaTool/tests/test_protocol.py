import unittest
from elatec_uid_tool.protocol import parse_search_tag_response


class ProtocolTests(unittest.TestCase):
    def test_em4102(self):
        tag = parse_search_tag_response(bytes.fromhex("00014028053D00C000D4"))
        self.assertEqual((tag.tag_type, tag.id_bit_count, tag.id_hex), (64, 40, "3D00C000D4"))


if __name__ == "__main__":
    unittest.main()
