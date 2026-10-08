"""Checking GitHub for new releases and installing them. No Qt in here.

- Packaged .exe: download the release zip, verify it, and swap the files in after the app exits.
- Git checkout: `git pull` + refresh the Python requirements.
- Plain source folder: point the user at the release page.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scdl_gui import APP_VERSION, GITHUB_REPO
from scdl_gui.settings import app_dir, data_dir

RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "scdl-gui-windows-x64.zip"
EXE_NAME = "scdl-gui.exe"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_ERROR_FILE = "update-error.txt"
UPDATE_DIR_PREFIX = "scdl-gui-update-"
INSTALL_FLAG = "--install-update"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # for console tools (git, pip)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class UpdateError(Exception):
    """Shown to the user as-is."""


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    notes: str
    asset_url: str = ""
    asset_size: int = 0
    asset_sha256: str = ""


def parse_version(text: str) -> tuple[int, int, int] | None:
    """'v1.2.3' / '1.2' -> (1, 2, 3) / (1, 2, 0). Pre-releases ('1.2.0-rc1') -> None."""
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def parse_release(data: dict) -> Release | None:
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = (data.get("tag_name") or "").lstrip("v")
    if parse_version(version) is None:
        return None
    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), {})
    digest = asset.get("digest") or ""
    return Release(
        version=version,
        page_url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
        notes=(data.get("body") or "").strip(),
        asset_url=asset.get("browser_download_url") or "",
        asset_size=int(asset.get("size") or 0),
        asset_sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
    )


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"scdl-gui/{APP_VERSION}"})


def fetch_latest(timeout: float = 10) -> Release | None:
    """The newest published release, or None if there isn't one. Raises UpdateError on network trouble."""
    try:
        with urllib.request.urlopen(_request(RELEASES_API, "application/vnd.github+json"), timeout=timeout) as resp:
            return parse_release(json.load(resp))
    except urllib.error.HTTPError as err:
        if err.code == 404:  # no releases published yet
            return None
        raise UpdateError(f"GitHub answered {err.code}") from err
    except (OSError, ValueError) as err:
        raise UpdateError(f"Couldn't reach GitHub ({err})") from err


def install_kind() -> str:
    """'exe' (packaged), 'git' (a git checkout) or 'source' (unzipped source code)."""
    if getattr(sys, "frozen", False):
        return "exe"
    return "git" if (app_dir() / ".git").exists() else "source"


# ---------------------------------------------------------------- packaged app


def download_asset(release: Release, progress: Callable[[int, int], None] | None = None) -> Path:
    if not release.asset_url:
        raise UpdateError("This release has no Windows download attached.")
    target = Path(tempfile.mkdtemp(prefix=UPDATE_DIR_PREFIX)) / ASSET_NAME
    sha = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(_request(release.asset_url, "application/octet-stream"), timeout=30) as resp, \
                open(target, "wb") as out:
            total = int(resp.headers.get("Content-Length") or release.asset_size or 0)
            while chunk := resp.read(256 * 1024):
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as err:
        raise UpdateError(f"Download failed ({err})") from err
    if release.asset_size and done != release.asset_size:
        raise UpdateError("The download was incomplete. Please try again.")
    if release.asset_sha256 and sha.hexdigest() != release.asset_sha256.lower():
        raise UpdateError("The download didn't match GitHub's checksum, so it wasn't installed.")
    return target


def _find_app_root(extracted: Path) -> Path:
    for exe in extracted.rglob(EXE_NAME):
        return exe.parent
    raise UpdateError(f"The update doesn't contain {EXE_NAME}.")


def prepare_exe_update(zip_path: Path) -> Path:
    """Unpack the update; returns the folder holding the new scdl-gui.exe."""
    staging = zip_path.parent / "files"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
    except (zipfile.BadZipFile, OSError) as err:
        raise UpdateError(f"Couldn't unpack the update ({err})") from err
    return _find_app_root(staging)


def start_installer(new_app: Path) -> None:
    """Run the *new* exe in --install-update mode; it waits for this app to exit, copies itself over
    the installed copy and restarts it. It's a windowed program, so no console ever appears.
    The caller should quit right after."""
    subprocess.Popen(
        [str(new_app / EXE_NAME), INSTALL_FLAG, str(new_app), str(app_dir()), str(os.getpid())],
        creationflags=DETACHED, close_fds=True,
    )


def wait_for_exit(pid: int, timeout_seconds: float) -> bool:
    """True once process `pid` has ended (or never existed); False on timeout."""
    import ctypes

    synchronize, wait_timeout = 0x00100000, 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True  # already gone
    try:
        return kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000)) != wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _copy_with_retries(source: Path, target: Path, attempts: int, delay: float) -> None:
    for attempt in range(attempts):
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
            return
        except OSError:  # e.g. antivirus or Explorer briefly holding a file
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def install_update(source: Path, target: Path, old_pid: int, *, attempts: int = 10, delay: float = 1.0) -> bool:
    """--install-update mode: copy the new app over the old one, then start it. Never raises -
    failures are left for the app to show on its next start."""
    ok = True
    try:
        if not wait_for_exit(old_pid, timeout_seconds=120):
            raise UpdateError("the old version didn't close")
        _copy_with_retries(source, target, attempts, delay)
    except (OSError, UpdateError) as err:
        ok = False
        (data_dir() / UPDATE_ERROR_FILE).write_text(
            f"Copying the new version into {target} failed: {err}", encoding="utf-8")
    subprocess.Popen([str(target / EXE_NAME)], creationflags=DETACHED, close_fds=True, cwd=str(target))
    return ok


def clean_update_leftovers() -> None:
    """Remove downloaded updates from earlier runs (each is ~60 MB)."""
    for folder in Path(tempfile.gettempdir()).glob(f"{UPDATE_DIR_PREFIX}*"):
        shutil.rmtree(folder, ignore_errors=True)  # one still in use is retried next start


def take_update_error() -> str:
    """Message left by a failed install, shown once on the next start."""
    path = data_dir() / UPDATE_ERROR_FILE
    if not path.exists():
        return ""
    try:
        message = path.read_text(encoding="utf-8", errors="replace").strip()
    finally:
        path.unlink(missing_ok=True)
    return message


# ---------------------------------------------------------------- git checkout


def console_python() -> str:
    python = Path(sys.executable)
    sibling = python.with_name("python.exe")
    return str(sibling if python.name.lower() == "pythonw.exe" and sibling.exists() else python)


def git_update() -> str:
    """Pull the latest code and refresh dependencies. Returns a short log; raises UpdateError."""
    root = app_dir()
    steps = [
        ["git", "-C", str(root), "pull", "--ff-only"],
        [console_python(), "-m", "pip", "install", "--disable-pip-version-check", "-q",
         "-r", str(root / "requirements.txt")],
    ]
    log = []
    for command in steps:
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    creationflags=NO_WINDOW, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise UpdateError(f"'{command[0]}' couldn't run ({err})") from err
        log.append((result.stdout + result.stderr).strip())
        if result.returncode != 0:
            raise UpdateError(f"'{' '.join(command[:3])}' failed:\n{log[-1][-600:]}")
    return "\n".join(filter(None, log))


def restart_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else sys.executable), str(app_dir() / "scdl-gui.pyw")]
