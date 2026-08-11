import tempfile
from pathlib import Path

from app.pcap_tools import TsharkInspector


def test_filename_sanitization_and_library():
    with tempfile.TemporaryDirectory() as d:
        x = TsharkInspector(d)
        p = x.save_upload("../../x weird?.pcapng", b"abcd")
        assert p.parent == Path(d)
        assert p.name.endswith(".pcapng")
        rows = x.list_files()
        assert len(rows) == 1 and rows[0]["name"] == p.name
