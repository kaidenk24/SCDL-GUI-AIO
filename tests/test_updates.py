"""Tests for update checking/installing logic (no network)."""

import hashlib
import io
import json
import os
import subprocess
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

    def test_prepare_exe_update_returns_the_new_app_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / updates.ASSET_NAME
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("scdl-gui/scdl-gui.exe", b"exe")
                archive.writestr("scdl-gui/_internal/lib.dll", b"dll")
            new_app = updates.prepare_exe_update(zip_path)
            self.assertEqual(new_app, Path(tmp) / "files" / "scdl-gui")
            self.assertTrue((new_app / "_internal" / "lib.dll").is_file())

    def test_start_installer_runs_the_new_exe_detached(self):
        with mock.patch("subprocess.Popen") as popen:
            updates.start_installer(Path("C:/staging/scdl-gui"))
        command = popen.call_args.args[0]
        self.assertTrue(command[0].endswith("scdl-gui.exe"))
        self.assertEqual(command[1:2], [updates.INSTALL_FLAG])
        self.assertEqual(command[4], str(os.getpid()))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"APPDATA": str(self.root / "appdata")})
        self._env.start()
        self.source, self.target = self.root / "new", self.root / "installed"
        (self.source / "_internal").mkdir(parents=True)
        (self.source / "scdl-gui.exe").write_bytes(b"new exe")
        (self.source / "_internal" / "lib.dll").write_bytes(b"new lib")
        self.target.mkdir()
        (self.target / "scdl-gui.exe").write_bytes(b"old exe")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_wait_for_exit_on_a_process_that_is_already_gone(self):
        self.assertTrue(updates.wait_for_exit(0x7FFFFFF0, timeout_seconds=1))

    def test_wait_for_exit_waits_for_a_running_process(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        self.assertTrue(updates.wait_for_exit(child.pid, timeout_seconds=20))
        self.assertIsNotNone(child.poll())

    def test_wait_for_exit_times_out(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertFalse(updates.wait_for_exit(child.pid, timeout_seconds=0.3))
        finally:
            child.kill()
            child.wait()

    def test_install_update_copies_and_restarts(self):
        with mock.patch("subprocess.Popen") as popen:
            self.assertTrue(updates.install_update(self.source, self.target, 0x7FFFFFF0))
        self.assertEqual((self.target / "scdl-gui.exe").read_bytes(), b"new exe")
        self.assertEqual((self.target / "_internal" / "lib.dll").read_bytes(), b"new lib")
        self.assertEqual(popen.call_args.args[0], [str(self.target / "scdl-gui.exe")])
        self.assertEqual(updates.take_update_error(), "")

    def test_install_update_retries_a_briefly_locked_file(self):
        real_copytree = updates.shutil.copytree
        calls = []

        def flaky(src, *args, **kwargs):
            if Path(src) == self.source:  # copytree also calls itself for subfolders
                calls.append(1)
                if len(calls) == 1:
                    raise PermissionError("in use")
            return real_copytree(src, *args, **kwargs)

        with mock.patch("subprocess.Popen"), mock.patch.object(updates.shutil, "copytree", flaky):
            self.assertTrue(updates.install_update(self.source, self.target, 0x7FFFFFF0, delay=0))
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.target / "_internal" / "lib.dll").read_bytes(), b"new lib")

    def test_failed_install_still_restarts_and_reports(self):
        with mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(updates.shutil, "copytree", side_effect=PermissionError("denied")):
            self.assertFalse(updates.install_update(self.source, self.target, 0x7FFFFFF0, attempts=2, delay=0))
        popen.assert_called_once()  # the old version opens again rather than nothing at all
        self.assertIn("denied", updates.take_update_error())

    def test_clean_update_leftovers(self):
        leftover = self.root / f"{updates.UPDATE_DIR_PREFIX}abc"
        (leftover / "files").mkdir(parents=True)
        unrelated = self.root / "keep-me"
        unrelated.mkdir()
        with mock.patch("tempfile.gettempdir", return_value=str(self.root)):
            updates.clean_update_leftovers()
        self.assertFalse(leftover.exists())
        self.assertTrue(unrelated.exists())


class MoreDownloadTests(unittest.TestCase):
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
