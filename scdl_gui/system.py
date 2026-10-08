"""Windows integration: Start menu / desktop shortcuts and one-click installs of helper tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scdl_gui import APP_NAME
from scdl_gui.settings import app_dir, resource_path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BACKGROUND_ARG = "--background"  # start hidden in the notification area (used by the Startup shortcut)


@dataclass(frozen=True)
class Tool:
    name: str
    winget_id: str
    download_page: str


FFMPEG = Tool("FFmpeg", "Gyan.FFmpeg", "https://www.gyan.dev/ffmpeg/builds/")
NODE = Tool("Node.js", "OpenJS.NodeJS.LTS", "https://nodejs.org/en/download")


def has_winget() -> bool:
    return shutil.which("winget") is not None


def winget_install_args(tool: Tool) -> list[str]:
    return [
        "install", "--id", tool.winget_id, "--exact", "--source", "winget", "--silent",
        "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity",
    ]


def launch_target() -> tuple[str, str]:
    """(program, arguments) that start the app without a console window."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else python), f'"{app_dir() / "scdl-gui.pyw"}"'


def shortcut_folders() -> dict[str, Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    return {
        "Start menu": appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        "Desktop": Path.home() / "Desktop",
    }


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_shortcut(link: Path, extra_arguments: str = "") -> bool:
    """Create a .lnk shortcut to the app (via Windows' own WScript.Shell)."""
    program, arguments = launch_target()
    arguments = f"{arguments} {extra_arguments}".strip()
    icon = resource_path("assets", "icon.ico")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(str(link)) + ");"
        f"$s.TargetPath = {_ps_quote(program)}; $s.Arguments = {_ps_quote(arguments)};"
        f"$s.WorkingDirectory = {_ps_quote(str(app_dir()))}; $s.IconLocation = {_ps_quote(str(icon) + ',0')};"
        f"$s.Description = {_ps_quote('Download SoundCloud playlists as MP3s')}; $s.Save()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, creationflags=NO_WINDOW, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and link.exists()


def create_shortcuts(places: list[str]) -> list[Path]:
    """Start menu / desktop shortcuts. Returns the ones created."""
    created = []
    for place in places:
        folder = shortcut_folders()[place]
        link = folder / f"{APP_NAME}.lnk"
        if folder.is_dir() and _write_shortcut(link):
            created.append(link)
    return created


def startup_link() -> Path:
    appdata = Path(os.environ.get("APPDATA", ""))
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{APP_NAME}.lnk"


def set_start_with_windows(enabled: bool) -> bool:
    """Add or remove the Startup shortcut that opens the app in the notification area. True if it worked."""
    link = startup_link()
    if not enabled:
        try:
            link.unlink(missing_ok=True)
        except OSError:
            return False
        return True
    return link.parent.is_dir() and _write_shortcut(link, BACKGROUND_ARG)
