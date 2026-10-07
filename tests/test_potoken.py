"""Tests for setting up the automatic PO-token generator (no network, no npm)."""

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

from scdl_gui import engine, potoken  # noqa: E402
from scdl_gui.settings import Settings  # noqa: E402

VERSION = "2.0.1"


def source_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"provider-{VERSION}/README.md", "readme")
        archive.writestr(f"provider-{VERSION}/server/package.json", "{}")
        archive.writestr(f"provider-{VERSION}/server/src/generate_once.ts", "// ts")
    return buffer.getvalue()


class PotTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def make_install(self, version: str, complete: bool = True) -> None:
        folder = potoken.pot_root() / version
        (folder / "plugins").mkdir(parents=True)
        (folder / "plugins" / potoken.PLUGIN_ASSET).write_bytes(b"zip")
        if complete:
            script = folder / "server" / potoken.SCRIPT
            script.parent.mkdir(parents=True)
            script.write_text("// js", encoding="utf-8")
        (potoken.pot_root() / potoken.STATE_FILE).write_text(json.dumps({"version": version}), encoding="utf-8")


class InstalledTests(PotTestCase):
    def test_nothing_installed(self):
        self.assertIsNone(potoken.installed())

    def test_complete_install_is_found(self):
        self.make_install(VERSION)
        install = potoken.installed()
        self.assertEqual(install.version, VERSION)
        self.assertTrue(str(install.server_home).endswith(os.path.join(VERSION, "server")))

    def test_half_finished_install_is_ignored(self):
        self.make_install(VERSION, complete=False)
        self.assertIsNone(potoken.installed())

    def test_version_compare(self):
        self.assertTrue(potoken.is_newer("2.0.2", "2.0.1"))
        self.assertFalse(potoken.is_newer("2.0.1", "2.0.1"))

    def test_worker_env_only_when_switched_on(self):
        self.make_install(VERSION)
        env = engine._pot_env(Settings())
        self.assertTrue(env["SCDL_POT_SERVER_HOME"].endswith("server"))
        self.assertEqual(engine._pot_env(Settings(auto_po_token=False)), {"SCDL_POT_PLUGIN_DIR": "", "SCDL_POT_SERVER_HOME": ""})


class InstallTests(PotTestCase):
    def fake_get(self, url, timeout=60):
        return b"plugin zip" if url.endswith(potoken.PLUGIN_ASSET) else source_zip()

    def fake_run(self, command, cwd, log, step):
        self.commands.append([Path(c).name if i < 2 else c for i, c in enumerate(command)])
        if "tsc" in command[1]:  # compiling produces the script
            (cwd / potoken.SCRIPT).parent.mkdir(parents=True, exist_ok=True)
            (cwd / potoken.SCRIPT).write_text("// js", encoding="utf-8")
        return VERSION if "--version" in command else ""

    def run_install(self):
        self.commands = []
        with tempfile.TemporaryDirectory() as node_dir:
            node = Path(node_dir) / "node.exe"
            node.write_bytes(b"")
            (Path(node_dir) / "npm.cmd").write_bytes(b"")
            with mock.patch.object(potoken, "_get", self.fake_get), mock.patch.object(potoken, "_run", self.fake_run):
                return potoken.install(VERSION, str(node), lambda _msg: None)

    def test_install_steps_and_activation(self):
        self.make_install("1.9.0")  # an older version gets replaced
        install = self.run_install()
        self.assertEqual(potoken.installed(), install)
        self.assertEqual([c[:2] for c in self.commands], [
            ["npm.cmd", "ci"], ["node.exe", "tsc"], ["npm.cmd", "prune"], ["node.exe", "generate_once.js"],
        ])
        self.assertTrue((install.server_home / "src" / "generate_once.ts").is_file())
        self.assertFalse((potoken.pot_root() / "1.9.0").exists())

    def test_failed_build_does_not_activate(self):
        self.make_install("1.9.0")

        def failing_run(command, cwd, log, step):
            raise potoken.PotError("npm ci failed")

        with tempfile.TemporaryDirectory() as node_dir:
            node = Path(node_dir) / "node.exe"
            (Path(node_dir) / "npm.cmd").write_bytes(b"")
            with mock.patch.object(potoken, "_get", self.fake_get), mock.patch.object(potoken, "_run", failing_run):
                with self.assertRaises(potoken.PotError):
                    potoken.install(VERSION, str(node), lambda _msg: None)
        self.assertEqual(potoken.installed().version, "1.9.0")  # the working version stays active

    def test_missing_npm(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(potoken.PotError):
                potoken.install(VERSION, "Z:\\nowhere\\node.exe", lambda _msg: None)


if __name__ == "__main__":
    unittest.main()
