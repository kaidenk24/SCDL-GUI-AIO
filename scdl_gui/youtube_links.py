"""YouTube links in the queue (videos, playlists, channels): downloaded like scdl downloads SoundCloud links.

    --youtube -l URL --path BASE --name-format FMT --playlist-name-format FMT [--download-archive FILE | -c] ...

Takes the same arguments the app gives scdl (engine.worker_args) and prints the same yt-dlp lines, so the
app shows progress, "already have" and failures the same way. The same format, levelling, album and tag
steps as SoundCloud downloads; the audio is YouTube's best stream (256k with Premium + a PO token).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request

from scdl.patches.mutagen_postprocessor import MutagenPP
from scdl.patches.switch_outtmpl_preprocessor import OuttmplPP
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.common import PostProcessor

from scdl_gui import formats, worker
from scdl_gui.engine import guess_kind
from scdl_gui.youtube import youtube_opts

TOPIC_SUFFIX = " - Topic"  # YouTube's auto-generated artist channels: "Artist - Topic"
ARTIST_TITLE = re.compile(r"(?P<artist>.*?)\s+[-−–—―]\s*(?P<title>.*)")  # noqa: RUF001 - as scdl's --extract-artist
FILE_NAME_MAX = "240b"  # as scdl: 240 bytes per name (scdl patches yt-dlp to take this form)
OEMBED = "https://www.youtube.com/oembed?format=json&url="


def _artist(name: str) -> str:
    return name[: -len(TOPIC_SUFFIX)] if name.endswith(TOPIC_SUFFIX) else name


# ---------------------------------------------------------------- name lookup


def _oembed(url: str) -> dict | None:
    """Title and channel in one small request. None when YouTube won't say - it refuses videos whose owner
    turned off embedding (common for label music videos), so that's no sign the link is wrong."""
    web_url = url.replace("://music.youtube.com/", "://www.youtube.com/")
    request = urllib.request.Request(OEMBED + urllib.parse.quote(web_url, safe=""), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def describe(url: str) -> dict:
    """Name and kind of a link. Videos and playlists via oEmbed when possible - much quicker than yt-dlp's
    full video extraction; channels (and anything oEmbed won't describe) via yt-dlp."""
    kind = guess_kind(url)
    data = _oembed(url) if kind in ("YouTube video", "YouTube playlist") and "/browse/" not in url else None
    if data:
        return {"kind": kind, "title": data.get("title") or "", "uploader": _artist(data.get("author_name") or "")}
    with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": 1}) as ydl:
        info = ydl.extract_info(url, download=False, process=False) or {}
    channel = info.get("channel") or info.get("uploader") or ""
    title = channel if kind == "YouTube channel" else info.get("title")
    return {"kind": kind, "title": title or channel, "uploader": _artist(channel)}


# ---------------------------------------------------------------- download


class YouTubeTagsPP(PostProcessor):
    """Tags like SoundCloud downloads get: the artist without " - Topic", the artist from "Artist - Title"
    video titles when that's switched on, and the playlist as the album in "playlist" album mode."""

    def __init__(self, artist_from_title: bool, album_mode: str) -> None:
        super().__init__()
        self._artist_from_title = artist_from_title
        self._album_mode = album_mode

    def run(self, info):
        if info.get("uploader"):
            info["uploader"] = _artist(info["uploader"])
        match = ARTIST_TITLE.fullmatch(info.get("title") or "")
        if self._artist_from_title and match and not info.get("artist"):
            info["meta_artist"], info["meta_title"] = match["artist"], match["title"]
        if self._album_mode == "playlist" and info.get("playlist"):
            info["meta_album"] = info["playlist"]
            info["meta_album_artist"] = _artist(info.get("playlist_uploader") or "") or None
            info["meta_track"] = info.get("playlist_index")
        return [], info


class Output:
    """yt-dlp's messages, printed as yt-dlp prints them; errors also go to the failure log."""

    def __init__(self) -> None:
        self.errors = 0

    def debug(self, message: str) -> None:
        if not message.startswith("[debug] "):
            print(message, flush=True)

    info = debug

    def warning(self, message: str) -> None:
        print(f"WARNING: {message}", flush=True)

    def error(self, message: str) -> None:
        print(message, flush=True)
        if message.startswith("ERROR:"):  # yt-dlp also sends notices this way ("Deprecated Feature: ...")
            self.errors += 1
            worker.record_failure(message)


class Quiet:
    def debug(self, message: str) -> None:
        pass

    info = warning = error = debug


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="--youtube", add_help=False)
    parser.add_argument("-l", dest="url", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--name-format", required=True)
    parser.add_argument("--playlist-name-format", required=True)
    parser.add_argument("--download-archive")
    parser.add_argument("--extract-artist", action="store_true")
    parser.add_argument("--add-description", action="store_true")
    return parser.parse_known_args(args)[0]  # SoundCloud-only flags (--original-art, -c...) don't apply


def build_params(opts: argparse.Namespace, output: Output) -> dict:
    params = {
        **youtube_opts(),  # login, PO token, JavaScript runtime: YouTube's best (Premium) streams
        "quiet": False, "no_warnings": False, "noprogress": True, "noplaylist": False, "logger": output,
        "format": formats.source_format(worker.FORMAT, bool(worker.TARGET_LUFS)),
        "paths": {"home": opts.path},
        "outtmpl": {"default": opts.playlist_name_format},
        "outtmpl_na_placeholder": "",
        "trim_file_name": FILE_NAME_MAX,
        "ignoreerrors": True,  # one unavailable video doesn't stop the playlist
        "allow_playlist_files": False,
        "writethumbnail": True,
        "writedescription": opts.add_description,
        # YouTube's thumbnails are WebP, which MP3/M4A cover art can't hold.
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
    }
    if opts.download_archive:
        params["download_archive"] = opts.download_archive
    if worker.MAX_TRACKS > 0:
        params["playlist_items"] = f"1:{worker.MAX_TRACKS}"
    params.update(worker.output_params())
    return params


def open_youtube(params: dict, output: Output) -> YoutubeDL:
    """With the browser's YouTube login if it can be read; without it (lower quality, but working) if not -
    e.g. no Firefox profile, or a Chromium browser that keeps its cookies locked while it runs."""
    if "cookiesfrombrowser" not in params:
        return YoutubeDL(params)
    # yt-dlp reports an unreadable cookie store as an error (some versions while starting up): not a failed track.
    ydl = YoutubeDL({**params, "logger": Quiet()})
    try:
        _ = ydl.cookiejar  # read now, so a problem here doesn't stop the download part-way
    except Exception as e:  # yt-dlp raises plain Exceptions/OSErrors for unreadable cookie stores
        ydl.close()
        output.warning(f"Couldn't read your YouTube login, downloading without it: {str(e).splitlines()[0][:150]}")
        return YoutubeDL({k: v for k, v in params.items() if k != "cookiesfrombrowser"})
    ydl.params["logger"] = output
    return ydl


def download(args: list[str]) -> int:
    opts = parse_args(args)
    output = Output()
    with open_youtube(build_params(opts, output), output) as ydl:
        ydl.add_post_processor(OuttmplPP(opts.name_format, opts.playlist_name_format), "pre_process")
        ydl.add_post_processor(YouTubeTagsPP(opts.extract_artist, worker.ALBUM_MODE), "pre_process")
        if worker.ALBUM_MODE in ("title", "none"):
            ydl.add_post_processor(worker.AlbumModePP(worker.ALBUM_MODE), "pre_process")
        ydl.add_post_processor(worker.ExistingFilePP(), "before_dl")
        ydl.add_post_processor(worker.convert_pp(), "post_process")
        ydl.add_post_processor(MutagenPP(False), "post_process")
        ydl.download([opts.url])
    return 1 if output.errors else 0
