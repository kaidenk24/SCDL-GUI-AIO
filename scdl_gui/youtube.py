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
from concurrent.futures import ThreadPoolExecutor

import yt_dlp.globals
from scdl.patches.mutagen_postprocessor import MutagenPP
from yt_dlp import YoutubeDL

from scdl_gui import formats, worker
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
ALBUM_MODE = os.environ.get("SCDL_ALBUM_MODE", "title")  # title | playlist | none
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


def search_opts(**extra) -> dict:
    """Searching needs no login, PO token or JavaScript runtime - those only matter for downloading the
    audio (youtube_opts). Leaving them out saves reading the browser's cookies and solving YouTube's
    challenges for every result."""
    return {"quiet": True, "no_warnings": True, "noplaylist": True, **extra}


def _music_search(query: str) -> list[dict]:
    url = f"https://music.youtube.com/search?q={urllib.parse.quote_plus(query)}#songs"
    # playlistend: the search is a "playlist" of hundreds of songs; without it all of them are fetched.
    with YoutubeDL(search_opts(extract_flat="in_playlist", playlistend=MUSIC_RESULTS)) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return [e for e in (info.get("entries") or []) if e.get("id")][:MUSIC_RESULTS]


def _web_search(query: str) -> list[Candidate]:
    with YoutubeDL(search_opts(extract_flat="in_playlist")) as ydl:
        info = ydl.extract_info(f"ytsearch{WEB_RESULTS}:{query}", download=False) or {}
    return [
        Candidate(
            id=e["id"], url=f"https://www.youtube.com/watch?v={e['id']}", title=e.get("title") or "",
            channel=e.get("channel") or e.get("uploader") or "",
            duration=int(e["duration"]) if e.get("duration") else None, source="YouTube",
        )
        for e in (info.get("entries") or []) if e.get("id")
    ]


def _music_details(entry: dict) -> Candidate:
    """YouTube Music search results carry no artist/length; look each one up."""
    try:
        with YoutubeDL(search_opts()) as ydl:
            url = f"https://music.youtube.com/watch?v={entry['id']}"
            info = ydl.extract_info(url, download=False, process=False) or {}
    except Exception:  # a result we can't open is still worth showing by title
        info = {}
    artists = list(dict.fromkeys(info.get("artists") or ([info["artist"]] if info.get("artist") else [])))
    return Candidate(
        id=entry["id"], url=f"https://music.youtube.com/watch?v={entry['id']}",
        title=info.get("track") or info.get("title") or entry.get("title") or "",
        channel=", ".join(artists) or info.get("channel") or info.get("uploader") or "",
        duration=int(info["duration"]) if info.get("duration") else None, source="YouTube Music",
    )


def find_matches(track: dict, query: str = "") -> tuple[str, list[Candidate], list[str]]:
    """Both searches run at once, then the YouTube Music lookups run at once (each request is mostly
    waiting on the network)."""
    query = query.strip() or build_query(track)
    errors: list[str] = []
    # (Searching YouTube Music by ISRC returns unrelated songs, so artist + title it is.)
    with ThreadPoolExecutor(max_workers=MUSIC_RESULTS + 1) as pool:
        music = pool.submit(_music_search, query)
        web = pool.submit(_web_search, query)
        try:
            entries = list({e["id"]: e for e in music.result()}.values())
        except Exception as e:
            errors.append(f"YouTube Music search: {e}")
            entries = []
        details = [pool.submit(_music_details, entry) for entry in entries]
        try:
            found = web.result()
        except Exception as e:
            errors.append(f"YouTube search: {e}")
            found = []
        found += [d.result() for d in details]
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


def _artwork(track: dict) -> bytes | None:
    url = track.get("artwork") or ""
    if not url:
        return None
    if not FULL_ART:
        url = url.replace("-original.", "-t500x500.")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            return r.read()
    except OSError:
        return None


def tag_info(path: str, track: dict, youtube_url: str) -> dict:
    """What scdl's tagger writes: the SoundCloud track's details (not YouTube's), in any format."""
    info = {
        "filepath": path, "ext": os.path.splitext(path)[1][1:].lower(), "__real_download": True,
        "title": track.get("title") or "", "artist": track.get("uploader") or None, "genre": track.get("genre") or None,
        "upload_date": track.get("upload_date") or None, "webpage_url": track.get("sc_url") or None,
        "description": f"Audio from {youtube_url} (SoundCloud upload is DRM-protected)",
    }
    if ALBUM_MODE == "title":
        info["meta_album"] = info["title"]
    elif ALBUM_MODE == "playlist" and track.get("playlist"):
        info["meta_album"] = track["playlist"]
        info["meta_album_artist"] = track.get("owner") or None
        info["meta_track"] = str(track["playlist_index"]) if track.get("playlist_index") else None
    return info


def write_tags(ydl: YoutubeDL, path: str, track: dict, youtube_url: str) -> None:
    info = tag_info(path, track, youtube_url)
    art = _artwork(track)
    if art:
        cover = f"{os.path.splitext(path)[0]}.cover.jpg"
        with open(cover, "wb") as f:
            f.write(art)
        info["thumbnails"] = [{"filepath": cover}]  # the tagger embeds it, then deletes the file
    MutagenPP(True, ydl).run(info)


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


def _saved_file(info: dict, target: str) -> str:
    finished = [d.get("filepath") for d in info.get("requested_downloads") or []]
    found = [f for f in finished if f and os.path.exists(f)]
    if found:
        return found[0]
    ext = worker.FORMAT.ext
    if ext and os.path.exists(f"{target}.{ext}"):
        return f"{target}.{ext}"
    raise RuntimeError("the download finished but no audio file was produced")


def download_match(job: dict) -> tuple[str, str]:
    target, url, track = job["target"], job["url"], job["track"]
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    levelling = bool(worker.TARGET_LUFS)
    params = youtube_opts(format=formats.source_format(worker.FORMAT, levelling), outtmpl=target + ".%(ext)s",
                          overwrites=True, **worker.output_params())
    with YoutubeDL(params) as ydl:
        ydl.add_post_processor(worker.convert_pp(), when="post_process")
        info = ydl.extract_info(url, download=True) or {}
        path = _saved_file(info, target)
        write_tags(ydl, path, track, url)
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
