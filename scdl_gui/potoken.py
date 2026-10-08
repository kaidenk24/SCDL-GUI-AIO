"""Automatic YouTube PO tokens, so YouTube Music Premium accounts get 256k+ audio.

Uses bgutil-ytdlp-pot-provider (GPL-3.0, https://github.com/Brainicism/bgutil-ytdlp-pot-provider). It's
downloaded on demand into the app's data folder - not bundled - and runs through the user's Node.js:
- plugins/<release zip>  : the yt-dlp plugin (loaded via yt_dlp.globals.plugin_dirs)
- server/                : the token generator (npm ci, compiled with tsc, dev packages pruned)
Each version lives in its own folder and only becomes active once it fully works. No Qt in here.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scdl_gui import APP_VERSION
from scdl_gui.settings import data_dir
from scdl_gui.updates import parse_version

REPO = "Brainicism/bgutil-ytdlp-pot-provider"
PLUGIN_ASSET = "bgutil-ytdlp-pot-provider.zip"
STATE_FILE = "installed.json"
SCRIPT = Path("build") / "generate_once.js"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NPM_TIMEOUT_SECONDS = 15 * 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Log = Callable[[str], None]


class PotError(Exception):
    """Shown to the user as-is."""


@dataclass(frozen=True)
class PotInstall:
    version: str
    folder: Path

    @property
    def plugin_dir(self) -> Path:
        return self.folder / "plugins"

    @property
    def server_home(self) -> Path:
        return self.folder / "server"


def pot_root() -> Path:
    return data_dir() / "potoken"


def installed() -> PotInstall | None:
    """The active, complete install, or None."""
    try:
        version = json.loads((pot_root() / STATE_FILE).read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    install = PotInstall(version=version, folder=pot_root() / version)
    complete = (install.plugin_dir / PLUGIN_ASSET).is_file() and (install.server_home / SCRIPT).is_file()
    return install if complete else None


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def _get(url: str, timeout: float = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"scdl-gui/{APP_VERSION}", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError) as err:
        raise PotError(f"Download failed ({url.rsplit('/', 1)[-1]}): {err}") from err


def latest_version() -> str:
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=15))
        version = str(data["tag_name"]).lstrip("v")
    except (ValueError, KeyError, TypeError) as err:
        raise PotError("Couldn't read the latest PO-token generator version from GitHub.") from err
    if parse_version(version) is None:
        raise PotError(f"Unexpected PO-token generator version '{version}'.")
    return version


def find_npm(node: str) -> str | None:
    """npm ships next to node.exe; fall back to PATH."""
    sibling = Path(node).with_name("npm.cmd")
    return str(sibling) if sibling.is_file() else shutil.which("npm")


def _run(command: list[str], cwd: Path, log: Log, step: str) -> str:
    log(step)
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, timeout=NPM_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise PotError(f"{step} failed: {err}") from err
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise PotError(f"{step} failed:\n{output[-800:]}")
    return output


def _extract_server(source_zip: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(source_zip)) as archive:
        top = archive.namelist()[0].split("/")[0]
        prefix = f"{top}/server/"
        members = [name for name in archive.namelist() if name.startswith(prefix) and not name.endswith("/")]
        if not members:
            raise PotError("The PO-token generator download has no server folder.")
        for name in members:
            target = destination / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def install(version: str, node: str, log: Log) -> PotInstall:
    """Download, build and verify `version`, then make it the active install."""
    npm = find_npm(node)
    if not npm:
        raise PotError("npm (part of Node.js) wasn't found. Reinstall Node.js from the Setup page.")
    target = PotInstall(version=version, folder=pot_root() / version)
    shutil.rmtree(target.folder, ignore_errors=True)  # leftovers of an interrupted attempt
    target.plugin_dir.mkdir(parents=True)
    base = f"https://github.com/{REPO}"

    log(f"Downloading the yt-dlp plugin {version}...")
    (target.plugin_dir / PLUGIN_ASSET).write_bytes(_get(f"{base}/releases/download/{version}/{PLUGIN_ASSET}"))
    log("Downloading the token generator...")
    _extract_server(_get(f"{base}/archive/refs/tags/{version}.zip"), target.server_home)

    home = target.server_home
    # --include=dev: TypeScript is needed to compile, even if NODE_ENV=production is set system-wide.
    _run([npm, "ci", "--include=dev", "--no-audit", "--no-fund"], home, log,
         "Installing its JavaScript packages (npm ci)...")
    _run([node, str(home / "node_modules" / "typescript" / "bin" / "tsc")], home, log, "Compiling the generator...")
    _run([npm, "prune", "--omit=dev", "--no-audit", "--no-fund"], home, log, "Removing build-only packages...")
    if not (home / SCRIPT).is_file():
        raise PotError("The generator didn't build (generate_once.js is missing).")
    output = _run([node, str(home / SCRIPT), "--version"], home, log, "Checking the generator runs...")
    if version not in output:
        raise PotError(f"The generator reported an unexpected version: {output[:200]}")

    (pot_root() / STATE_FILE).write_text(json.dumps({"version": version}), encoding="utf-8")
    _remove_other_versions(keep=version)
    log(f"Ready - automatic PO tokens {version}.")
    return target


def _remove_other_versions(keep: str) -> None:
    for folder in pot_root().iterdir():
        if folder.is_dir() and folder.name != keep:
            shutil.rmtree(folder, ignore_errors=True)  # a running download may still hold files; retried next time


def remove() -> None:
    shutil.rmtree(pot_root(), ignore_errors=True)
