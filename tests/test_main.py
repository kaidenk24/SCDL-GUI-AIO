"""Tests for the entry point's worker setup."""

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import main  # noqa: E402


class WorkerOutputTests(unittest.TestCase):
    def test_worker_output_is_switched_to_utf8(self):
        # A packaged build starts with the Windows code page (cp1252) on its pipes.
        out_bytes, err_bytes = io.BytesIO(), io.BytesIO()
        stdout = io.TextIOWrapper(out_bytes, encoding="cp1252", errors="strict")
        stderr = io.TextIOWrapper(err_bytes, encoding="cp1252", errors="backslashreplace")
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            main._use_utf8_output()
            print("SATØS ⧸ ＊", file=sys.stdout)
            print("hype remix⧸mashup", file=sys.stderr)
        self.assertEqual(out_bytes.getvalue().decode("utf-8").strip(), "SATØS ⧸ ＊")
        self.assertEqual(err_bytes.getvalue().decode("utf-8").strip(), "hype remix⧸mashup")

    def test_missing_streams_are_ignored(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            main._use_utf8_output()  # windowed app started without pipes: must not crash


if __name__ == "__main__":
    unittest.main()
