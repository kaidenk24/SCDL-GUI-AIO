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

    def test_drm_report_survives_a_cp1252_console(self):
        # Regression: "'charmap' codec can't encode character '\u29f8'" lost the DRM track.
        from scdl_gui import worker
        from scdl_gui.parsing import OutputParser

        class FakeYdl:
            def prepare_filename(self, info, outtmpl):
                return "E:\\hype remix\u29f8mashup\\SAT\u00d8S - Track.mp3"

        track = {"sc_id": "1", "title": "SAT\u00d8S - Track", "uploader": "x", "genre": "", "upload_date": ""}
        raw = io.BytesIO()
        strict_cp1252 = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(sys, "stdout", strict_cp1252), \
                mock.patch.dict(worker._output_templates, {True: "template"}):
            worker.report_drm(FakeYdl(), track, {"playlist": "hype remix/mashup", "playlist_index": 7})
            strict_cp1252.flush()
        event = OutputParser().feed(raw.getvalue().decode("ascii"))
        self.assertEqual(event.kind, "drm")
        self.assertEqual(event.data["target"], "E:\\hype remix\u29f8mashup\\SAT\u00d8S - Track")

    def test_missing_streams_are_ignored(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            main._use_utf8_output()  # windowed app started without pipes: must not crash


if __name__ == "__main__":
    unittest.main()
