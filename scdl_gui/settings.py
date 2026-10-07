"""User settings and the download queue, persisted as JSON in %APPDATA%."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from scdl_gui import APP_NAME

log = logging.getLogger(__name__)

# Job.folder values with special meaning.
FOLDER_AUTO = None  # use the save layout (Settings.folder_template)
FOLDER_ROOT = ""  # straight into the library folder

ARCHIVE_MODES = ("shared", "per_link", "files")
QUALITIES = ("V0", "320", "256", "V2", "192")
# Browsers yt-dlp can borrow cookies from. Firefox is the most reliable on Windows: recent
# Chromium browsers encrypt their cookies in a way that often can't be read while they run.
BROWSERS = ("firefox", "librewolf", "chrome", "edge", "brave", "opera", "vivaldi", "chromium")


@dataclass(frozen=True)
class Settings:
    library: str = ""
    folder_template: str = "{playlist}"
    file_template: str = "{title}"
    archive_mode: str = "shared"
    quality: str = "V0"
    normalize: bool = True
    target_lufs: float = -14.0
    use_originals: bool = True
    skip_previews: bool = True
    max_tracks: int = 0  # 0 = every track of each link
    full_art: bool = True
    album_tags: bool = True
    artist_from_title: bool = False
    save_description: bool = False
    use_login: bool = True
    cookie_browser: str = "firefox"  # browser whose SoundCloud/YouTube login is borrowed
    firefox_profile: str = ""  # "" = most recently used profile
    ffmpeg_path: str = ""  # "" = find ffmpeg on PATH
    youtube_fallback: bool = True  # find DRM-protected tracks on YouTube (you confirm each one)
    youtube_login: bool = True  # use the Firefox YouTube login
    youtube_po_token: str = ""  # optional; unlocks YouTube Music's 256k Premium audio
    new_link_folder: str | None = FOLDER_AUTO
    folders: tuple[str, ...] = ()
    lookup_names: bool = True
    show_details: bool = False
    check_updates: bool = True
    last_update_check: float = 0.0  # epoch seconds
    skipped_version: str = ""  # "Skip this version" on the update banner
    offered_shortcuts: bool = False  # first-run "add shortcuts?" question was asked

    def with_changes(self, **changes) -> Settings:
        return replace(self, **changes)


@dataclass
class Job:
    url: str
    folder: str | None = FOLDER_AUTO
    enabled: bool = True
    name: str = ""
    kind: str = ""
    status: str = "Queued"


def app_dir() -> Path:
    """Folder the app runs from (the .exe folder when packaged)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base.joinpath(*parts)


def default_library() -> str:
    """Music\\SoundCloud in the user's home folder."""
    return str(Path.home() / "Music" / "SoundCloud")


def data_dir() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _coerce(cls, raw: dict):
    """Build a dataclass from JSON, ignoring unknown keys and values of the wrong type."""
    defaults = cls() if cls is Settings else None
    values = {}
    for f in fields(cls):
        if f.name not in raw:
            continue
        value = raw[f.name]
        if f.name == "folders":
            value = tuple(str(v) for v in value) if isinstance(value, list) else ()
        elif defaults is not None:
            expected = type(getattr(defaults, f.name))
            if isinstance(getattr(defaults, f.name), float) and isinstance(value, int):
                value = float(value)
            if getattr(defaults, f.name) is not None and not isinstance(value, expected):
                continue
        values[f.name] = value
    return cls(**values)


def _validated(settings: Settings) -> Settings:
    changes = {}
    if settings.archive_mode not in ARCHIVE_MODES:
        changes["archive_mode"] = "shared"
    if settings.quality not in QUALITIES:
        changes["quality"] = "V0"
    if not -30 <= settings.target_lufs <= -5:
        changes["target_lufs"] = -14.0
    if settings.max_tracks < 0:
        changes["max_tracks"] = 0
    if settings.cookie_browser not in BROWSERS:
        changes["cookie_browser"] = "firefox"
    if not settings.library:
        changes["library"] = default_library()
    return settings.with_changes(**changes) if changes else settings


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        log.warning("Ignoring unreadable %s: %s", path, err)
        return None


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_settings() -> Settings:
    raw = _read_json(data_dir() / "settings.json")
    settings = _coerce(Settings, raw) if isinstance(raw, dict) else Settings()
    return _validated(settings)


def save_settings(settings: Settings) -> None:
    data = asdict(settings)
    data["folders"] = list(settings.folders)
    _write_json(data_dir() / "settings.json", data)


def load_queue() -> list[Job]:
    raw = _read_json(data_dir() / "queue.json")
    if not isinstance(raw, list):
        return []
    jobs = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            job = _coerce(Job, item)
            if job.status not in ("Queued", "Done") and not job.status.startswith("Done"):
                job.status = "Queued"  # interrupted runs restart cleanly
            jobs.append(job)
    return jobs


def save_queue(jobs: list[Job]) -> None:
    _write_json(data_dir() / "queue.json", [asdict(job) for job in jobs])
