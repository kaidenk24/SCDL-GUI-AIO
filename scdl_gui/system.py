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


def create_shortcuts(places: list[str]) -> list[Path]:
    """Create .lnk shortcuts (via Windows' own WScript.Shell). Returns the ones created."""
    program, arguments = launch_target()
    icon = resource_path("assets", "icon.ico")
    created = []
    for place in places:
        folder = shortcut_folders()[place]
        if not folder.is_dir():
            continue
        link = folder / f"{APP_NAME}.lnk"
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(str(link)) + ");"
            f"$s.TargetPath = {_ps_quote(program)}; $s.Arguments = {_ps_quote(arguments)};"
            f"$s.WorkingDirectory = {_ps_quote(str(app_dir()))}; $s.IconLocation = {_ps_quote(str(icon) + ',0')};"
            f"$s.Description = {_ps_quote('Download SoundCloud playlists as MP3s')}; $s.Save()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, creationflags=NO_WINDOW, timeout=30,
        )
        if result.returncode == 0 and link.exists():
            created.append(link)
    return created
