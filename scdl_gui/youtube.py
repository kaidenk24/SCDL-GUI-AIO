"""YouTube side of the download worker: search for DRM-protected tracks and download confirmed matches.

    --yt-search FILE    FILE = JSON list of {"key", "track", "query"?}; prints "@@YTMATCH {json}" per item
    --yt-download FILE  FILE = JSON {"key", "url", "target", "track", "archive"}; prints "@@YTDONE {json}"

Uses the browser's YouTube login (SCDL_YT_LOGIN=1), a JavaScript runtime (Node/Deno) for YouTube's
challenges, and - generated automatically (SCDL_POT_*), given by hand (SCDL_YT_PO_TOKEN) or provided
by an installed plugin - a PO token so the YouTube Music client can be used (Premium: 256k+ audio).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

import yt_dlp.globals
from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK, WOAF, ID3NoHeaderError
from yt_dlp import YoutubeDL

from scdl_gui import worker
from scdl_gui.engine import has_pot_plugin
from scdl_gui.matching import Candidate, build_query, rank

def _js_runtimes() -> dict:
    """The runtime the app found ('node:C:\\...\\node.exe'), else let yt-dlp look on PATH."""
    name, _, path = (os.environ.get("SCDL_JS_RUNTIME") or "").partition(":")
    if name and path:
        return {name: {"path": path}}
    return {"node": {"path": None}, "deno": {"path": None}}


YT_LOGIN = os.environ.get("SCDL_YT_LOGIN") == "1"
PO_TOKEN = (os.environ.get("SCDL_YT_PO_TOKEN") or "").strip()
POT_PLUGIN_DIR = os.environ.get("SCDL_POT_PLUGIN_DIR") or ""  # automatic PO tokens (see potoken.py)
POT_SERVER_HOME = os.environ.get("SCDL_POT_SERVER_HOME") or ""
if POT_PLUGIN_DIR:
    # Must be set before the first YoutubeDL is created - that's when yt-dlp loads plugins.
    yt_dlp.globals.plugin_dirs.value = [POT_PLUGIN_DIR, "default"]
FULL_ART = os.environ.get("SCDL_FULL_ART", "1") == "1"
ALBUM_TAGS = os.environ.get("SCDL_ALBUM_TAGS", "1") == "1"
JS_RUNTIMES = _js_runtimes()
MUSIC_RESULTS = 3
WEB_RESULTS = 6
MAX_CANDIDATES = 8
MATCH_MARKER = "@@YTMATCH "
DONE_MARKER = "@@YTDONE "


def youtube_opts(**extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "js_runtimes": JS_RUNTIMES, **extra}
    if YT_LOGIN:
        opts["cookiesfrombrowser"] = (worker.BROWSER_NAME, worker.PROFILE, None, None)
    automatic = bool(POT_PLUGIN_DIR and POT_SERVER_HOME)
    if PO_TOKEN or automatic or has_pot_plugin():
        # The YouTube Music client serves Premium's 256k AAC / 282k Opus, but only with a PO token.
        client_args = {"player_client": ["web_music", "default"]}
        if PO_TOKEN:
            client_args["po_token"] = [f"web_music.gvs+{PO_TOKEN}"]
        opts["extractor_args"] = {"youtube": client_args}
        if automatic:
            opts["extractor_args"]["youtubepot-bgutilscript"] = {"server_home": [POT_SERVER_HOME]}
    return opts


# ---------------------------------------------------------------- search


def _music_search(ydl: YoutubeDL, query: str) -> list[dict]:
    url = f"https://music.youtube.com/search?q={urllib.parse.quote_plus(query)}#songs"
    info = ydl.extract_info(url, download=False) or {}
    return [e for e in (info.get("entries") or []) if e.get("id")][:MUSIC_RESULTS]


def _web_search(ydl: YoutubeDL, query: str) -> list[Candidate]:
    info = ydl.extract_info(f"ytsearch{WEB_RESULTS}:{query}", download=False) or {}
    return [
        Candidate(
            id=e["id"], url=f"https://www.youtube.com/watch?v={e['id']}", title=e.get("title") or "",
            channel=e.get("channel") or e.get("uploader") or "",
            duration=int(e["duration"]) if e.get("duration") else None, source="YouTube",
        )
        for e in (info.get("entries") or []) if e.get("id")
    ]


def _music_details(ydl: YoutubeDL, entry: dict) -> Candidate:
    """YouTube Music search results carry no artist/length; look each one up."""
    try:
        info = ydl.extract_info(f"https://music.youtube.com/watch?v={entry['id']}", download=False, process=False) or {}
    except Exception:  # a result we can't open is still worth showing by title
        info = {}
    artists = info.get("artists") or ([info["artist"]] if info.get("artist") else [])
    return Candidate(
        id=entry["id"], url=f"https://music.youtube.com/watch?v={entry['id']}",
        title=info.get("track") or info.get("title") or entry.get("title") or "",
        channel=", ".join(artists) or info.get("channel") or info.get("uploader") or "",
        duration=int(info["duration"]) if info.get("duration") else None, source="YouTube Music",
    )


def find_matches(track: dict, query: str = "") -> tuple[str, list[Candidate], list[str]]:
    query = query.strip() or build_query(track)
    found: list[Candidate] = []
    errors: list[str] = []
    music_entries: list[dict] = []
    with YoutubeDL(youtube_opts(extract_flat="in_playlist")) as flat:
        # (Searching YouTube Music by ISRC returns unrelated songs, so artist + title it is.)
        try:
            music_entries += _music_search(flat, query)
        except Exception as e:
            errors.append(f"YouTube Music search: {e}")
        try:
            found += _web_search(flat, query)
        except Exception as e:
            errors.append(f"YouTube search: {e}")
    seen: set[str] = set()
    unique = [e for e in music_entries if not (e["id"] in seen or seen.add(e["id"]))]
    with YoutubeDL(youtube_opts()) as full:
        found += [_music_details(full, entry) for entry in unique]
    return query, rank(track, found)[:MAX_CANDIDATES], errors


def search_items(items: list[dict]) -> None:
    for item in items:
        result = {"key": item["key"]}
        try:
            query, candidates, errors = find_matches(item["track"], item.get("query") or "")
            result.update(query=query, candidates=[c.to_dict() for c in candidates])
            if not candidates and errors:
                result["error"] = errors[0][:300]
        except Exception as e:  # report and move on to the next track
            result["error"] = str(e)[:300]
        worker.emit(MATCH_MARKER, result)


# ---------------------------------------------------------------- download & tag


def _artwork(track: dict) -> tuple[bytes, str] | None:
    url = track.get("artwork") or ""
    if not url:
        return None
    if not FULL_ART:
        url = url.replace("-original.", "-t500x500.")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            data = r.read()
    except OSError:
        return None
    return data, "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def write_tags(path: str, track: dict, youtube_url: str) -> None:
    """Tag the MP3 like scdl tags SoundCloud downloads (SoundCloud metadata, not YouTube's)."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.clear()
    tags.add(TIT2(encoding=3, text=track.get("title") or ""))
    if track.get("uploader"):
        tags.add(TPE1(encoding=3, text=track["uploader"]))
    if ALBUM_TAGS and track.get("playlist"):
        tags.add(TALB(encoding=3, text=track["playlist"]))
        if track.get("owner"):
            tags.add(TPE2(encoding=3, text=track["owner"]))
        if track.get("playlist_index"):
            tags.add(TRCK(encoding=3, text=str(track["playlist_index"])))
    if track.get("genre"):
        tags.add(TCON(encoding=3, text=track["genre"]))
    date = track.get("upload_date") or ""
    if len(date) == 8:
        tags.add(TDRC(encoding=3, text=f"{date[:4]}-{date[4:6]}-{date[6:]}"))
    if track.get("sc_url"):
        tags.add(WOAF(url=track["sc_url"]))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=f"Audio from {youtube_url} (SoundCloud upload is DRM-protected)"))
    art = _artwork(track)
    if art:
        tags.add(APIC(encoding=3, mime=art[1], type=3, desc="Cover", data=art[0]))
    tags.save(path)


def remember_in_archive(archive: str, sc_id: str) -> None:
    """Record the SoundCloud track as downloaded so future runs skip it."""
    if not archive or not sc_id:
        return
    line = f"soundcloud {sc_id}"
    try:
        with open(archive, encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""
    if line in existing.splitlines():
        return
    with open(archive, "a", encoding="utf-8") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + line + "\n")


def download_match(job: dict) -> tuple[str, str]:
    target, url, track = job["target"], job["url"], job["track"]
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    params = youtube_opts(format="bestaudio/best", outtmpl=target + ".%(ext)s", final_ext="mp3", overwrites=True)
    if worker.FFMPEG:
        params["ffmpeg_location"] = worker.FFMPEG
    if not worker.TARGET_LUFS:
        params["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": worker.EXTRACT_AUDIO_QUALITY}
        ]
    with YoutubeDL(params) as ydl:
        if worker.TARGET_LUFS:
            ydl.add_post_processor(worker.LoudnessMp3PP(), when="post_process")
        info = ydl.extract_info(url, download=True) or {}
    path = target + ".mp3"
    if not os.path.exists(path):
        raise RuntimeError("the download finished but no MP3 was produced")
    write_tags(path, track, url)
    remember_in_archive(job.get("archive") or "", track.get("sc_id") or "")
    abr = info.get("abr")
    source = f"{info.get('acodec') or 'audio'} {round(abr)}k" if abr else (info.get("format_id") or "audio")
    return path, f"from YouTube ({source})"


def main(args: list[str]) -> int:
    mode, path = args[0], args[1]
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if mode == "--yt-search":
        search_items(payload)
        return 0
    result = {"key": payload["key"]}
    try:
        saved, message = download_match(payload)
        result.update(ok=True, path=saved, message=message)
    except Exception as e:  # report to the app instead of crashing the worker
        result.update(ok=False, message=str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__)
    worker.emit(DONE_MARKER, result)
    return 0 if result["ok"] else 1
