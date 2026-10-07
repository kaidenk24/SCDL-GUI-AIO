"""Tests for update checking/installing logic (no network)."""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import updates  # noqa: E402

PAYLOAD = b"fake zip bytes"


def release_json(tag="v1.4.0", **extra) -> dict:
    return {
        "tag_name": tag, "html_url": "https://github.com/x/y/releases/tag/" + tag, "body": "Fixes",
        "draft": False, "prerelease": False,
        "assets": [{
            "name": updates.ASSET_NAME, "browser_download_url": "https://example.invalid/app.zip",
            "size": len(PAYLOAD), "digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(),
        }],
        **extra,
    }


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updates.parse_version("1.2"), (1, 2, 0))
        self.assertIsNone(updates.parse_version("1.2.0-rc1"))
        self.assertIsNone(updates.parse_version("latest"))

    def test_is_newer(self):
        self.assertTrue(updates.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.9.0", "1.0.0"))
        self.assertFalse(updates.is_newer("garbage", "1.0.0"))


class ReleaseTests(unittest.TestCase):
    def test_parse_release(self):
        release = updates.parse_release(release_json())
        self.assertEqual(release.version, "1.4.0")
        self.assertEqual(release.asset_size, len(PAYLOAD))
        self.assertEqual(release.asset_sha256, hashlib.sha256(PAYLOAD).hexdigest())

    def test_drafts_prereleases_and_odd_tags_are_ignored(self):
        self.assertIsNone(updates.parse_release(release_json(draft=True)))
        self.assertIsNone(updates.parse_release(release_json(prerelease=True)))
        self.assertIsNone(updates.parse_release(release_json(tag="nightly")))

    def test_release_without_windows_asset(self):
        release = updates.parse_release({**release_json(), "assets": []})
        self.assertEqual(release.asset_url, "")

    def test_fetch_latest_handles_no_releases(self):
        error = updates.urllib.error.HTTPError(updates.RELEASES_API, 404, "Not Found", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            self.assertIsNone(updates.fetch_latest())

    def test_fetch_latest_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(updates.UpdateError):
                updates.fetch_latest()

    def test_fetch_latest_parses_response(self):
        body = json.dumps(release_json("v2.0.0")).encode()
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            self.assertEqual(updates.fetch_latest().version, "2.0.0")


class DownloadTests(unittest.TestCase):
    def test_download_verifies_checksum(self):
        release = updates.parse_release(release_json())
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(PAYLOAD)):
            path = updates.download_asset(release)
        self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_download_rejects_tampered_file(self):
        release = updates.parse_release(release_json())
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"tampered bytes")):
            with self.assertRaises(updates.UpdateError):
                updates.download_asset(release)

    def test_prepare_exe_update_writes_installer_script(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as appdata, \
                mock.patch.dict(os.environ, {"APPDATA": appdata}):
            zip_path = Path(tmp) / updates.ASSET_NAME
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("scdl-gui/scdl-gui.exe", b"exe")
                archive.writestr("scdl-gui/_internal/lib.dll", b"dll")
            script = updates.prepare_exe_update(zip_path)
            text = script.read_text(encoding="utf-8")
            self.assertIn("robocopy", text)
            self.assertIn(str(Path(tmp) / "files" / "scdl-gui"), text)
            self.assertIn(str(os.getpid()), text)

    def test_prepare_rejects_zip_without_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / updates.ASSET_NAME
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("readme.txt", b"nothing here")
            with self.assertRaises(updates.UpdateError):
                updates.prepare_exe_update(zip_path)

    def test_update_error_message_is_shown_once(self):
        with tempfile.TemporaryDirectory() as appdata, mock.patch.dict(os.environ, {"APPDATA": appdata}):
            (updates.data_dir() / updates.UPDATE_ERROR_FILE).write_text("copy failed", encoding="utf-8")
            self.assertEqual(updates.take_update_error(), "copy failed")
            self.assertEqual(updates.take_update_error(), "")


if __name__ == "__main__":
    unittest.main()
