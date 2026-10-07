"""Turns the download worker's raw output (scdl/yt-dlp log lines) into progress events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

# Structured lines from the worker: prefix -> event kind (payload is JSON).
JSON_EVENTS = {
    "@@DESCRIBE ": "describe",
    "@@DRM ": "drm",
    "@@YTMATCH ": "ytmatch",
    "@@YTDONE ": "ytdone",
    "@@LOGIN ": "login",
}

_PLAYLIST = re.compile(r"^\[download\] Downloading playlist: (.+)$")
_ITEM = re.compile(r"^\[download\] Downloading item (\d+) of (\d+)")
_EXTRACTING = re.compile(r"^\[soundcloud\] Extracting URL: https?://[^/]+/(.+)$")
_DESTINATION = re.compile(r"^\[download\] Destination: (.+)$")
_SAVED = re.compile(r'^\[Mutagen\] Adding metadata to "(.+)"')
_ARCHIVED = re.compile(r"^\[download\] (?:\d+: )?(.+?) has already been recorded in the archive")
_EXISTS = re.compile(r"^\[download\] (.+?) has already been downloaded")
_ERROR = re.compile(r"^ERROR: (?:\[[\w:]+\] )?(?:[\w-]+: )?(.+)$")
_RATE = re.compile(r"^\[rate-limit\] (.+)$")
_LOUDNESS = re.compile(r"^\[LoudnessMp3\] (.+)$")

_FRIENDLY_ERRORS = (
    ("drm protected", "Protected by DRM - SoundCloud doesn't allow downloading this one"),
    ("requested format is not available", "Only a 30-second preview is available (Go+ track - log in with Go+)"),
    ("http error 404", "Not found - deleted, private, or the link is wrong"),
    ("http error 403", "Access denied - private or blocked in your region"),
    ("unable to extract client id", "Couldn't reach SoundCloud - check your internet connection"),
    ("getaddrinfo failed", "No internet connection"),
    ("timed out", "SoundCloud took too long to answer - try again"),
)


def friendly_error(message: str) -> str:
    lowered = message.lower()
    for needle, text in _FRIENDLY_ERRORS:
        if needle in lowered:
            return text
    return message.strip()


def _stem(path: str) -> str:
    return PureWindowsPath(path.strip().strip('"')).stem


@dataclass(frozen=True)
class Event:
    kind: str  # playlist | item | track | saved | skipped | error | rate | loudness | + JSON_EVENTS kinds
    text: str = ""
    current: int = 0
    total: int = 0
    data: dict = field(default_factory=dict)


class OutputParser:
    """Stateful: remembers which track is in progress so errors can name it."""

    def __init__(self) -> None:
        self._current_slug = ""

    def feed(self, line: str) -> Event | None:
        line = line.rstrip()
        if line.startswith("@@"):
            return self._json_event(line)
        if m := _ITEM.match(line):
            return Event("item", current=int(m.group(1)), total=int(m.group(2)))
        if m := _PLAYLIST.match(line):
            return Event("playlist", m.group(1))
        if m := _EXTRACTING.match(line):
            self._current_slug = m.group(1)
            return None
        if m := _DESTINATION.match(line):
            return Event("track", _stem(m.group(1)))
        if m := _SAVED.match(line):
            return Event("saved", _stem(m.group(1)))
        if m := _ARCHIVED.match(line):
            return Event("skipped", m.group(1))
        if m := _EXISTS.match(line):
            return Event("skipped", _stem(m.group(1)))
        if m := _ERROR.match(line):
            where = self._current_slug
            data = {"track": where, "raw": line, "drm": "drm protected" in line.lower()}
            return Event("error", friendly_error(m.group(1)), data=data)
        if m := _RATE.match(line):
            return Event("rate", m.group(1))
        if m := _LOUDNESS.match(line):
            return Event("loudness", m.group(1))
        return None

    @staticmethod
    def _json_event(line: str) -> Event | None:
        for prefix, kind in JSON_EVENTS.items():
            if line.startswith(prefix):
                try:
                    return Event(kind, data=json.loads(line[len(prefix):]))
                except ValueError:
                    return None
        return None


@dataclass
class JobCounts:
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    to_match: int = 0  # DRM-protected, sent to the YouTube matches page

    def summary(self) -> str:
        parts = [f"{self.saved} new"]
        if self.skipped:
            parts.append(f"{self.skipped} already had")
        if self.to_match:
            parts.append(f"{self.to_match} to match on YouTube")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts)
