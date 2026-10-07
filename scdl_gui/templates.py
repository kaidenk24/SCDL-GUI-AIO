"""Friendly folder/file templates ({playlist}\\{title}) -> yt-dlp output templates, and previews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath


@dataclass(frozen=True)
class Token:
    name: str
    field: str  # yt-dlp field expression
    label: str
    hint: str


TOKENS = (
    Token("title", "title", "Title", "Track title"),
    Token("artist", "uploader", "Artist", "SoundCloud account that uploaded the track"),
    Token("playlist", "playlist", "Playlist", "Playlist name (or e.g. 'djexample (Likes)')"),
    Token("owner", "playlist_uploader", "Playlist owner", "Who made the playlist"),
    Token("index", "playlist_index", "Track #", "Position in the playlist, zero-padded (07)"),
    Token("year", "upload_date>%Y", "Year", "Year the track was uploaded"),
    Token("date", "upload_date>%Y-%m-%d", "Date", "Upload date (2025-06-14)"),
    Token("genre", "genre", "Genre", "Genre set by the uploader"),
    Token("id", "id", "Track ID", "SoundCloud's numeric track ID"),
)
FIELDS = {t.name: t.field for t in TOKENS}
PLAYLIST_ONLY = ("playlist", "owner", "index")

_TOKEN_RE = re.compile(r"\{(\w+)\}([ ._,-]*)")
_SINGLE_STRIP_RE = re.compile(r"\{(" + "|".join(PLAYLIST_ONLY) + r")\}[ ._,-]*", re.IGNORECASE)
_ANY_TOKEN_RE = re.compile(r"\{(\w+)\}")
_INVALID_CHARS_RE = re.compile(r'[<>:"|?*]')

FOLDER_PRESETS = (
    ("One folder per playlist", "{playlist}"),
    ("Playlist owner, then playlist", "{owner}\\{playlist}"),
    ("One folder per artist", "{artist}"),
    ("Playlist, then artist", "{playlist}\\{artist}"),
    ("One folder per year", "{year}"),
    ("No folders (everything in the library folder)", ""),
)
FILE_PRESETS = (
    ("Title", "{title}"),
    ("Track # - Title", "{index} - {title}"),
    ("Artist - Title", "{artist} - {title}"),
    ("Track # - Artist - Title", "{index} - {artist} - {title}"),
    ("Title [Track ID]", "{title} [{id}]"),
)


def unknown_tokens(template: str) -> list[str]:
    return [name for name in _ANY_TOKEN_RE.findall(template) if name.lower() not in FIELDS]


def to_ytdl(template: str, single_track: bool = False) -> str:
    """Convert a friendly template. Literal text is escaped; a separator right after a token
    ("{genre} - ") disappears when the token is empty. single_track drops playlist-only tokens."""
    text = template.replace('"', "").replace("\\", "/")
    if single_track:
        text = _SINGLE_STRIP_RE.sub("", text)
    out, last = [], 0
    for match in _TOKEN_RE.finditer(text):
        out.append(text[last:match.start()].replace("%", "%%"))
        field = FIELDS.get(match.group(1).lower())
        separator = match.group(2)
        end = match.end()
        # {index} stays plain so yt-dlp zero-pads it; it's always set inside playlists.
        conditional = separator and end < len(text) and text[end] != "/" and field != "playlist_index"
        if field is None:
            out.append(match.group(0).replace("%", "%%"))
        elif conditional:
            out.append(f"%({field}&{{}}{separator}|)s")
        else:
            out.append(f"%({field})s{separator}")
        last = end
    out.append(text[last:].replace("%", "%%"))
    return "".join(out)


@dataclass(frozen=True)
class OutputTarget:
    base: str  # scdl --path
    playlist_format: str  # --playlist-name-format
    single_format: str  # --name-format


def output_target(library: str, layout: str, file_template: str) -> OutputTarget:
    """Split a folder layout (relative, or an absolute path that may contain tokens) into
    the scdl base path and the yt-dlp name formats."""
    layout = (layout or "").strip()
    base = library
    if PureWindowsPath(layout).drive:
        token_at = layout.find("{")
        fixed_end = len(layout) if token_at < 0 else max(layout.rfind("\\", 0, token_at), layout.rfind("/", 0, token_at))
        base = layout[:fixed_end] if fixed_end > 0 else layout
        if re.fullmatch(r"[A-Za-z]:", base):
            base += "\\"
        layout = layout[fixed_end:]
    folder = layout.strip("\\/ ")
    file_part = (file_template or "").strip() or "{title}"
    relative = f"{folder}/{file_part}" if folder else file_part
    return OutputTarget(
        base=base,
        playlist_format=_tidy(to_ytdl(relative)) + ".%(ext)s",
        single_format=_tidy(to_ytdl(relative, single_track=True)) + ".%(ext)s",
    )


def _tidy(fmt: str) -> str:
    """No empty or leading path parts: a leading '/' would make the path drive-absolute."""
    return re.sub(r"/{2,}", "/", fmt).lstrip("/")


def clean_folder_name(name: str) -> str:
    """Folder names typed by the user: drop characters Windows can't store. Keeps tokens,
    subfolders (a\\b) and absolute paths (D:\\Music)."""
    name = name.strip().replace("/", "\\")
    drive = PureWindowsPath(name).drive
    rest = _INVALID_CHARS_RE.sub("", name[len(drive):]).strip("\\ ")
    if drive:
        return f"{drive}\\{rest}" if rest else f"{drive}\\"
    return rest


# ---------------------------------------------------------------- previews

SAMPLE_TRACKS = (
    (
        "Playlist track",
        {
            "title": "Summer Nights (VIP Mix)", "uploader": "DJ Example", "playlist": "Summer House",
            "playlist_uploader": "djexample", "playlist_index": 7, "n_entries": 15,
            "__last_playlist_index": 15, "upload_date": "20250614", "genre": "House", "id": "1234567890",
        },
    ),
    (
        "Liked track",
        {
            "title": "Golden Hour", "uploader": "Aurora Vale", "playlist": "djexample (Likes)",
            "playlist_index": 3, "n_entries": 250, "__last_playlist_index": 250,
            "upload_date": "20220520", "genre": "Dance", "id": "1210987654",
        },
    ),
    (
        "Single track link",
        {"title": "Night Drive", "uploader": "nightowl", "upload_date": "20250110", "genre": "House", "id": "2005738627"},
    ),
)

_preview_ydl = None


def _evaluator():
    global _preview_ydl
    if _preview_ydl is None:
        from yt_dlp import YoutubeDL

        _preview_ydl = YoutubeDL({"quiet": True, "outtmpl_na_placeholder": ""})
    return _preview_ydl


def preview_paths(library: str, layout: str, file_template: str) -> list[tuple[str, str]]:
    """Example output paths for a playlist track, a liked track and a single track."""
    target = output_target(library, layout, file_template)
    ydl = _evaluator()
    previews = []
    for label, info in SAMPLE_TRACKS:
        fmt = target.single_format if "playlist" not in info else target.playlist_format
        relative = ydl.evaluate_outtmpl(fmt, {**info, "ext": "mp3"}, True)
        parts = [p for p in re.split(r"[\\/]+", relative) if p.strip()]
        previews.append((label, str(PureWindowsPath(target.base, *parts))))
    return previews
