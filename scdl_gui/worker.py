"""Download worker: runs in its own process (one per queued link), started by the app.

Wraps scdl's entry point and adds: MP3 conversion with optional loudness levelling,
Firefox-cookie login, pacing for SoundCloud's API rate limit, Go+ preview rejection,
playlist handling for non-set lists (likes, stations...) and a failure log.

Modes (after --worker):
    <scdl arguments>          download (settings via SCDL_* environment variables)
    --check-cookies           print '@@LOGIN {"soundcloud": bool, "youtube": bool}'
    --describe URL [URL..]    print one "@@DESCRIBE {json}" line per link
    --yt-search FILE          find YouTube matches for DRM tracks (see youtube.py)
    --yt-download FILE        download a confirmed YouTube match (see youtube.py)

With SCDL_YT_FALLBACK=1, DRM-protected tracks are reported as '@@DRM {json}' lines.
"""

import json
import logging
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import yt_dlp

if getattr(sys, "frozen", False):
    # scdl does `import yt_dlp.__init__`; PyInstaller's importer loads that as a separate (broken)
    # package. Point it at the real yt_dlp module instead.
    sys.modules.setdefault("yt_dlp.__init__", yt_dlp)
    yt_dlp.__init__ = yt_dlp  # the attribute a normal `import yt_dlp.__init__` sets on the package

import scdl.scdl as scdl_main  # noqa: E402 - must come after the alias above
from scdl.patches.switch_outtmpl_preprocessor import OuttmplPP
from yt_dlp import YoutubeDL
from yt_dlp.extractor import soundcloud as sc_extractor
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import ExtractorError, PostProcessingError, prepend_extension, replace_extension

QUALITY = os.environ.get("SCDL_MP3_QUALITY", "V0").upper()  # V0, V2, 320, 256, 192
TARGET_LUFS = os.environ.get("SCDL_TARGET_LUFS") or None  # None = no loudness levelling
BROWSER_NAME = os.environ.get("SCDL_BROWSER") or "firefox"  # where logins are borrowed from
BROWSER = BROWSER_NAME if os.environ.get("SCDL_SC_LOGIN", "1") == "1" else None  # SoundCloud login
PROFILE = os.environ.get("SCDL_COOKIE_PROFILE") or None
FAILED_LOG = os.environ.get("SCDL_FAILED_LOG") or None
SOURCE_URL = os.environ.get("SCDL_SOURCE_URL", "")
RATE_STATE = os.environ.get("SCDL_RATE_STATE") or None
ALLOW_PREVIEWS = os.environ.get("SCDL_ALLOW_PREVIEWS") == "1"
FFMPEG = os.environ.get("SCDL_FFMPEG") or None
MAX_TRACKS = int(os.environ.get("SCDL_MAX_TRACKS") or 0)  # 0 = all tracks of each link
YT_FALLBACK = os.environ.get("SCDL_YT_FALLBACK") == "1"  # report DRM tracks for a YouTube match
DRM_MARKER = "@@DRM "

# SoundCloud allows ~600 API requests per 10 minutes; stay well under it.
API_BUDGET = 500
API_WINDOW_SECONDS = 600
RATE_LIMIT_BACKOFF_SECONDS = (30, 60, 120, 240)

TRUE_PEAK_DBTP = -1.0
# High LRA target keeps loudnorm in linear (pure gain) mode instead of compressing dynamics.
TARGET_LRA = 20
IS_VBR = QUALITY.startswith("V")
MP3_QUALITY_ARGS = ["-q:a", QUALITY[1:]] if IS_VBR else ["-b:a", f"{QUALITY}k"]
EXTRACT_AUDIO_QUALITY = QUALITY[1:] if IS_VBR else QUALITY
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CODEC_RANK = {"aac": 2, "mp3": 1, "opus": 0}
STREAM_QUALITY_RANK = {"hq": 2, "sq": 1, "lq": 0}
DRM_PROTOCOL_PREFIXES = ("ctr-", "cbc-")

SET_EXTRACTORS = {"SoundcloudSet", "SoundcloudPlaylist"}
LIST_KINDS = {
    "likes": "Likes",
    "reposts": "Reposts",
    "tracks": "Uploads",
    "sets": "All playlists",
    "albums": "All albums",
    "spotlight": "Spotlight",
    "recommended": "Related",
}

if FFMPEG:
    FFmpegPostProcessor._ffmpeg_location.set(FFMPEG)


# ---------------------------------------------------------------- rate limiting


class ApiPacer:
    """Spaces SoundCloud API calls under the rate limit; the state file carries across runs."""

    def __init__(self, state_path):
        self._state_path = state_path

    def _recent_calls(self, now):
        try:
            with open(self._state_path, encoding="utf-8") as f:
                stamps = [float(line) for line in f if line.strip()]
        except (OSError, ValueError):
            return []
        return [s for s in stamps if now - s < API_WINDOW_SECONDS]

    def wait_turn(self):
        if not self._state_path:
            return
        now = time.time()
        calls = self._recent_calls(now)
        if len(calls) >= API_BUDGET:
            delay = calls[len(calls) - API_BUDGET] + API_WINDOW_SECONDS - now
            print(f"[rate-limit] Pausing {delay:.0f}s to stay under SoundCloud's API limit", flush=True)
            time.sleep(max(delay, 0))
            now = time.time()
            calls = self._recent_calls(now)
        calls.append(now)
        with open(self._state_path, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{s:.3f}" for s in calls[-API_BUDGET:]))


PACER = ApiPacer(RATE_STATE)
_original_call_api = sc_extractor.SoundcloudBaseIE._call_api
_original_extract_info_dict = sc_extractor.SoundcloudBaseIE._extract_info_dict


def paced_call_api(self, *args, **kwargs):
    """Every SoundCloud API request: pace it, and wait out a 429 instead of skipping the track."""
    for delay in (*RATE_LIMIT_BACKOFF_SECONDS, None):
        PACER.wait_turn()
        try:
            return _original_call_api(self, *args, **kwargs)
        except ExtractorError as e:
            is_rate_limited = isinstance(e.cause, HTTPError) and e.cause.status == 429
            if delay is None or not is_rate_limited:
                raise
            print(f"[rate-limit] SoundCloud asked to slow down; retrying in {delay}s", flush=True)
            time.sleep(delay)


def stream_rank(transcoding):
    codec = (transcoding.get("preset") or "").partition("_")[0]
    protocol = (transcoding.get("format") or {}).get("protocol") or ""
    return (
        not transcoding.get("snipped"),
        CODEC_RANK.get(codec, -1),
        STREAM_QUALITY_RANK.get(transcoding.get("quality"), -1),
        protocol == "progressive",
    )


def pick_streams(transcodings):
    """Best stream plus an MP3 backup. yt-dlp spends one API call per stream it considers,
    and SoundCloud lists ~8 near-duplicates per track."""

    def protocol(t):
        return (t.get("format") or {}).get("protocol") or ""

    drm = [t for t in transcodings if protocol(t).startswith(DRM_PROTOCOL_PREFIXES)]  # skipped for free
    usable = [t for t in transcodings if t not in drm and not (t.get("preset") or "").startswith("abr")]
    if not usable:
        return transcodings
    best = max(usable, key=stream_rank)
    picked = [best]
    mp3s = [t for t in usable if (t.get("preset") or "").startswith("mp3")]
    if mp3s and best not in mp3s:
        picked.append(max(mp3s, key=stream_rank))
    return drm + picked


def lean_extract_info_dict(self, info, *args, **kwargs):
    transcodings = (info.get("media") or {}).get("transcodings")
    if transcodings:
        info = {**info, "media": {**info["media"], "transcodings": pick_streams(transcodings)}}
    try:
        return _original_extract_info_dict(self, info, *args, **kwargs)
    except ExtractorError as e:
        if YT_FALLBACK and "drm protected" in str(e).lower():
            _drm_stash["track"] = soundcloud_metadata(info)
        raise


sc_extractor.SoundcloudBaseIE._call_api = paced_call_api
sc_extractor.SoundcloudBaseIE._extract_info_dict = lean_extract_info_dict


# ---------------------------------------------------------------- DRM tracks -> YouTube match requests

def emit(marker: str, payload: dict) -> None:
    """A structured line for the app. ASCII-only JSON (non-ASCII is \\u-escaped inside the JSON), so it
    survives any console encoding - a raw '⧸' in a path once crashed this on cp1252 pipes."""
    print(marker + json.dumps(payload), flush=True)


_drm_stash: dict = {}  # filled by the extractor, reported once the playlist position is known
_output_templates: dict = {}  # in_playlist -> scdl output template
_archive_path = ""


def soundcloud_metadata(info: dict) -> dict:
    """What's needed to find the track elsewhere and tag the replacement like the original."""
    publisher = info.get("publisher_metadata") or {}
    user = info.get("user") or {}
    artwork = info.get("artwork_url") or user.get("avatar_url") or ""
    date = (info.get("display_date") or info.get("created_at") or "")[:10].replace("-", "")
    return {
        "sc_id": str(info.get("id") or ""),
        "sc_url": info.get("permalink_url") or "",
        "title": info.get("title") or "",
        "uploader": user.get("username") or "",
        "artist": publisher.get("artist") or "",
        "album": publisher.get("album_title") or publisher.get("release_title") or "",
        "isrc": publisher.get("isrc") or "",
        "duration": round((info.get("full_duration") or info.get("duration") or 0) / 1000) or None,
        "genre": info.get("genre") or "",
        "upload_date": date if date.isdigit() else "",
        "artwork": artwork.replace("-large.", "-original.") if artwork else "",
    }


def report_drm(ydl: YoutubeDL, track: dict, extra: dict) -> None:
    """Print a @@DRM record, incl. the file path scdl would have used, for the app to match."""
    in_playlist = extra.get("playlist") is not None or extra.get("playlist_index") is not None
    name_info = {
        **{k: v for k, v in extra.items() if k.startswith(("playlist", "n_entries", "__last_playlist"))},
        "id": track["sc_id"], "title": track["title"], "uploader": track["uploader"],
        "genre": track["genre"] or None, "upload_date": track["upload_date"] or None, "ext": "mp3",
    }
    target = ""
    template = _output_templates.get(in_playlist)
    if template:
        target = os.path.splitext(ydl.prepare_filename(name_info, outtmpl=template))[0]
    record = {
        **track,
        "playlist": extra.get("playlist") or "",
        "playlist_index": extra.get("playlist_index"),
        "owner": extra.get("playlist_uploader") or "",
        "target": os.path.normpath(target) if target else "",
        "archive": _archive_path,
        "source_link": SOURCE_URL,
    }
    emit(DRM_MARKER, record)


_original_extract_info = YoutubeDL.extract_info


def extract_info_reporting_drm(self, url, download=True, ie_key=None, extra_info=None, *args, **kwargs):
    result = _original_extract_info(self, url, download, ie_key, extra_info, *args, **kwargs)
    track = _drm_stash.pop("track", None)
    if track:
        report_drm(self, track, dict(extra_info or {}))
    return result


# ---------------------------------------------------------------- post-processing


class LoudnessMp3PP(FFmpegPostProcessor):
    """Convert to MP3 with two-pass EBU R128 loudness normalisation (pure gain when possible)."""

    def _measure(self, path):
        scan = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA={TARGET_LRA}:print_format=json"
        cmd = [self.executable, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", scan, "-f", "null", "-"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW
        )
        if result.returncode != 0:
            raise PostProcessingError(f"Loudness scan failed: {result.stderr.strip()[-300:]}")
        stats = json.loads(result.stderr[result.stderr.rindex("{"): result.stderr.rindex("}") + 1])
        return stats if math.isfinite(float(stats["input_i"])) else None  # None = silent track

    def _sample_rate(self, path):
        streams = self.get_metadata_object(path).get("streams") or []
        rates = [s.get("sample_rate") for s in streams if s.get("codec_type") == "audio"]
        return str(rates[0]) if rates and rates[0] else "44100"

    def run(self, info):
        source = info["filepath"]
        target = replace_extension(source, "mp3")
        output = prepend_extension(target, "temp") if target == source else target
        stats = self._measure(source)
        opts = ["-vn"]
        if stats:
            self.to_screen(f"{float(stats['input_i']):.1f} LUFS -> {TARGET_LUFS} LUFS")
            gain = (
                f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA={TARGET_LRA}"
                f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true"
            )
            # loudnorm upsamples to 192 kHz internally; keep the source rate.
            opts += ["-af", gain, "-ar", self._sample_rate(source)]
        opts += ["-c:a", "libmp3lame", *MP3_QUALITY_ARGS]
        self.run_ffmpeg(source, output, opts)
        if output != target:
            os.replace(output, target)
        info["filepath"] = target
        info["ext"] = "mp3"
        return ([source] if source != target else []), info


def outtmpl_run(self, info):
    """scdl's OuttmplPP only treats sets (lists with an owner) as playlists, so likes/stations
    got the single-track file name and no album tags. Any playlist entry counts here."""
    in_playlist = info.get("playlist") is not None or info.get("playlist_index") is not None
    self._downloader.params["outtmpl"]["default"] = self._outtmpls[in_playlist]
    if not in_playlist:
        for meta in ("track", "album_artist", "album"):
            info[f"meta_{meta}"] = None
    return [], info


OuttmplPP.run = outtmpl_run
_original_build = scdl_main._build_ytdl_params


def build_params(url, scdl_args):
    global _archive_path
    url, params, postprocessors = _original_build(url, scdl_args)
    _output_templates.update({
        in_playlist: scdl_main._build_ytdl_output_filename(scdl_args, in_playlist) for in_playlist in (False, True)
    })
    _archive_path = scdl_args.get("download_archive") or ""
    if not ALLOW_PREVIEWS:
        # Never save 30s Go+ snippets as if they were full tracks.
        params["format"] = params.get("format", "ba") + "[format_id!*=preview]"
    params["final_ext"] = "mp3"
    # Skip playlist-level files: the playlist cover lands as a stray "..jpg" (scdl filename
    # patch bug) and isn't needed since every track embeds its own art.
    params["allow_playlist_files"] = False
    if FFMPEG:
        params["ffmpeg_location"] = FFMPEG
    if MAX_TRACKS > 0:
        params["playlist_items"] = f"1:{MAX_TRACKS}"
    if TARGET_LUFS:
        # Must run before scdl's tagger (the first post_process entry) so tags land on the MP3.
        first_post = next((i for i, (_, when) in enumerate(postprocessors) if when == "post_process"), len(postprocessors))
        postprocessors.insert(first_post, (LoudnessMp3PP(), "post_process"))
    else:
        params["postprocessors"] = [
            *params.get("postprocessors", []),
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": EXTRACT_AUDIO_QUALITY,
                "nopostoverwrites": False,
            },
        ]
    if BROWSER:
        params["cookiesfrombrowser"] = (BROWSER, PROFILE, None, None)
    return url, params, postprocessors


# ---------------------------------------------------------------- helpers & modes


class FailureLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1
        if not FAILED_LOG:
            return
        reason = record.getMessage().replace("\r", " ").replace("\n", " ")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(FAILED_LOG, "a", encoding="utf-8") as f:
                f.write(f"# {stamp} | source={SOURCE_URL} | reason={reason}\n")
        except OSError as err:
            print(f"[worker] Could not write the failure log: {err}", flush=True)


def cookie_opts():
    return {"cookiesfrombrowser": (BROWSER, PROFILE, None, None)} if BROWSER else {}


def expand_short_link(url):
    """on.soundcloud.com share links have no yt-dlp extractor; follow the redirect."""
    if urllib.parse.urlparse(url).hostname != "on.soundcloud.com":
        return url
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.geturl().split("?")[0].rstrip("/")


def check_cookies():
    from yt_dlp.cookies import extract_cookies_from_browser

    jar = extract_cookies_from_browser(BROWSER_NAME, PROFILE)
    soundcloud = any(c.name == "oauth_token" and c.domain.endswith("soundcloud.com") for c in jar)
    youtube = any(c.domain.endswith("youtube.com") and c.name in ("LOGIN_INFO", "SAPISID", "__Secure-3PAPISID") for c in jar)
    emit("@@LOGIN ", {"soundcloud": soundcloud, "youtube": youtube})


def describe_kind(url, info):
    if info.get("_type") != "playlist":
        return "Track"
    if info.get("extractor_key") in SET_EXTRACTORS:
        return "Playlist"
    if info.get("extractor_key") == "SoundcloudTrackStation":
        return "Station"
    return LIST_KINDS.get(url.rstrip("/").rsplit("/", 1)[-1], "Profile")


def describe(urls):
    """Look up the name and kind of each link without downloading anything."""
    opts = {"quiet": True, "no_warnings": True, "allowed_extractors": ["soundcloud.*"], **cookie_opts()}
    with YoutubeDL(opts) as ydl:
        for url in urls:
            result = {"url": url}
            try:
                resolved = expand_short_link(url)
                info = ydl.extract_info(resolved, download=False, process=False)
                result.update(
                    resolved=resolved,
                    kind=describe_kind(resolved, info),
                    title=info.get("title"),
                    uploader=info.get("uploader"),
                )
            except Exception as e:  # report per link, keep going
                result["error"] = (str(e).strip().splitlines() or ["lookup failed"])[0][:200]
            emit("@@DESCRIBE ", result)


def main(args):
    """args: everything after --worker."""
    if args[:1] == ["--check-cookies"]:
        check_cookies()
        return 0
    if args[:1] == ["--describe"]:
        describe(args[1:])
        return 0
    if args[:1] in (["--yt-search"], ["--yt-download"]):
        from scdl_gui import youtube

        return youtube.main(args)
    if YT_FALLBACK:
        YoutubeDL.extract_info = extract_info_reporting_drm
    failures = FailureLog()
    logging.getLogger(scdl_main.__name__).addHandler(failures)
    argv = ["scdl", *args]
    url_pos = argv.index("-l") + 1
    argv[url_pos] = expand_short_link(argv[url_pos])
    scdl_main._build_ytdl_params = build_params
    sys.argv = argv  # scdl reads its options with docopt from sys.argv
    scdl_main._main()
    return 1 if failures.count else 0
