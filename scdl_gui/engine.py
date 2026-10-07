"""Turns settings + queued links into download-worker commands. No Qt in here."""

from __future__ import annotations

import configparser
import functools
import importlib.metadata
import os
import re
import shutil
import sys
from pathlib import Path

from scdl_gui.settings import FOLDER_AUTO, Job, Settings, app_dir
from scdl_gui.templates import output_target

URL_RE = re.compile(r"https?://(?:www\.|m\.|on\.)?soundcloud\.com/[^\s\"'<>|]+", re.IGNORECASE)
FAILED_LOG_NAME = "soundcloud-failed.txt"
LAUNCHER_NAME = "scdl-gui.pyw"
ARCHIVE_NAME = "download_archive.txt"
ARCHIVES_DIR_NAME = ".archives"

_LIST_SUFFIX_KINDS = {
    "likes": "Likes",
    "reposts": "Reposts",
    "tracks": "Uploads",
    "sets": "All playlists",
    "albums": "All albums",
    "spotlight": "Spotlight",
    "recommended": "Related",
}


def extract_links(text: str) -> list[str]:
    """All soundcloud.com links in any pasted text, cleaned of tracking junk, in order, no repeats."""
    links: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in URL_RE.finditer(line):
            # Drop ?si=..&utm_.. tracking; private-link secrets live in the path.
            link = re.split(r"[?#]", match.group(0), maxsplit=1)[0].rstrip("/")
            if link not in links:
                links.append(link)
    return links


def guess_kind(url: str) -> str:
    """Quick, offline guess of what a link points at (the lookup refines it)."""
    host_and_path = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    host, _, path = host_and_path.partition("/")
    if host.lower().startswith("on."):
        return "Share link"
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "Unknown"
    if parts[0] == "stations":
        return "Station"
    if len(parts) == 1:
        return "Profile"
    if parts[1] == "sets" and len(parts) >= 3:
        return "Playlist"
    if len(parts) == 2 and parts[1] in _LIST_SUFFIX_KINDS:
        return _LIST_SUFFIX_KINDS[parts[1]]
    if len(parts) == 3 and parts[2] in _LIST_SUFFIX_KINDS:
        return "Related"
    return "Track"


def link_slug(url: str) -> str:
    path = re.sub(r"^https?://[^/]+/", "", url)
    return re.sub(r"[^\w\-]+", "_", path).strip("_") or "link"


def worker_command() -> list[str]:
    """How to start the download worker: the packaged exe, or this Python with the launcher."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    python = Path(sys.executable)
    console_python = python.with_name("python.exe")  # pythonw has no stdout to read
    exe = str(console_python if python.name.lower() == "pythonw.exe" and console_python.exists() else python)
    return [exe, str(app_dir() / LAUNCHER_NAME), "--worker"]


@functools.lru_cache(maxsize=1)
def has_pot_plugin() -> bool:
    """A yt-dlp PO-token provider plugin (e.g. bgutil-ytdlp-pot-provider) is installed."""
    for dist in importlib.metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if "pot-provider" in name or "getpot" in name:
            return True
    return False


def _first_existing(paths) -> str | None:
    for path in paths:
        if path and Path(path).is_file():
            return str(path)
    return None


def _winget_paths(exe: str, package_glob: str) -> list[Path]:
    """Where winget puts tools; PATH of an already-running app doesn't include fresh installs."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    found = [local / "Microsoft" / "WinGet" / "Links" / exe]
    packages = local / "Microsoft" / "WinGet" / "Packages"
    if packages.is_dir():
        found += sorted(packages.glob(f"{package_glob}/**/{exe}"))
    return found


def find_js_runtime() -> str | None:
    """YouTube needs Node.js or Deno to solve its playback challenges."""
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return shutil.which("node") or shutil.which("deno") or _first_existing([
        program_files / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe",
        Path.home() / ".deno" / "bin" / "deno.exe",
        *_winget_paths("node.exe", "OpenJS.NodeJS*"),
        *_winget_paths("deno.exe", "DenoLand.Deno*"),
    ])


def find_ffmpeg(settings: Settings) -> str | None:
    if settings.ffmpeg_path:
        return settings.ffmpeg_path if Path(settings.ffmpeg_path).exists() else None
    return shutil.which("ffmpeg") or _first_existing([
        app_dir() / "ffmpeg" / "ffmpeg.exe",
        *_winget_paths("ffmpeg.exe", "Gyan.FFmpeg*"),
        *_winget_paths("ffmpeg.exe", "BtbN.FFmpeg*"),
    ])


def js_runtime_spec() -> str:
    """'node:C:\\...\\node.exe' for the worker, or '' if none was found."""
    runtime = find_js_runtime()
    if not runtime:
        return ""
    return f"{'deno' if Path(runtime).stem.lower() == 'deno' else 'node'}:{runtime}"


def failed_log_path(library: str) -> Path:
    return Path(library) / FAILED_LOG_NAME


def archive_path(settings: Settings, job: Job) -> Path | None:
    library = Path(settings.library)
    if settings.archive_mode == "shared":
        return library / ARCHIVE_NAME
    if settings.archive_mode == "per_link":
        return library / ARCHIVES_DIR_NAME / f"{link_slug(job.url)}.txt"
    return None


def worker_args(settings: Settings, job: Job) -> list[str]:
    """scdl arguments for one queued link."""
    layout = settings.folder_template if job.folder is FOLDER_AUTO else job.folder
    target = output_target(settings.library, layout, settings.file_template)
    args = [
        "-l", job.url,
        "--path", target.base,
        "--no-playlist-folder",
        "--name-format", target.single_format,
        "--playlist-name-format", target.playlist_format,
        "--hide-progress",
    ]
    archive = archive_path(settings, job)
    if archive is None:
        args.append("-c")  # skip tracks whose file already exists
    else:
        archive.parent.mkdir(parents=True, exist_ok=True)
        args += ["--download-archive", str(archive)]
    if settings.full_art:
        args.append("--original-art")
    if not settings.use_originals:
        args.append("--no-original")
    if not settings.album_tags:
        args.append("--no-album-tag")
    if settings.artist_from_title:
        args.append("--extract-artist")
    if settings.save_description:
        args.append("--add-description")
    return args


def worker_env(settings: Settings, source_url: str = "") -> dict[str, str]:
    return {
        "SCDL_MP3_QUALITY": settings.quality,
        "SCDL_TARGET_LUFS": f"{settings.target_lufs:g}" if settings.normalize else "",
        "SCDL_BROWSER": settings.cookie_browser,
        "SCDL_SC_LOGIN": "1" if settings.use_login else "0",
        "SCDL_COOKIE_PROFILE": settings.firefox_profile if settings.cookie_browser == "firefox" else "",
        "SCDL_JS_RUNTIME": js_runtime_spec(),
        "SCDL_FAILED_LOG": str(failed_log_path(settings.library)),
        "SCDL_SOURCE_URL": source_url,
        "SCDL_RATE_STATE": str(Path(os.environ.get("TEMP", ".")) / "scdl_api_calls.txt"),
        "SCDL_ALLOW_PREVIEWS": "0" if settings.skip_previews else "1",
        "SCDL_MAX_TRACKS": str(max(settings.max_tracks, 0)),
        "SCDL_FFMPEG": find_ffmpeg(settings) or "",
        "SCDL_YT_FALLBACK": "1" if settings.youtube_fallback else "0",
        "SCDL_YT_LOGIN": "1" if settings.youtube_login else "0",
        "SCDL_YT_PO_TOKEN": settings.youtube_po_token.strip(),
        "SCDL_FULL_ART": "1" if settings.full_art else "0",
        "SCDL_ALBUM_TAGS": "1" if settings.album_tags else "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _decode_text(data: bytes) -> str:
    """profiles.ini may be UTF-8, UTF-8 with BOM, or UTF-16 (e.g. after being edited in Notepad)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def firefox_profiles() -> list[tuple[str, str]]:
    """(name, folder) of every Firefox profile that has a cookie store."""
    root = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    ini = root / "profiles.ini"
    if not ini.exists():
        return []
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(_decode_text(ini.read_bytes()))
    except (configparser.Error, OSError, UnicodeDecodeError):
        return []
    profiles = []
    for section in parser.sections():
        if not section.startswith("Profile") or not parser.has_option(section, "Path"):
            continue
        raw = parser.get(section, "Path")
        relative = parser.get(section, "IsRelative", fallback="1") == "1"
        folder = (root / raw) if relative else Path(raw)
        if (folder / "cookies.sqlite").exists():
            profiles.append((parser.get(section, "Name", fallback=folder.name), str(folder)))
    return profiles
