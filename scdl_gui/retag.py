"""Rewrite the Album tags of songs already in the library to match the album setting. Tags only -
the audio is never touched. MP3 and WAV (ID3), M4A, FLAC, Opus and Ogg. No Qt in here."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.id3 import ID3, TALB, ID3NoHeaderError
from mutagen.wave import WAVE

RETAG_MODES = ("title", "none")  # "playlist" can't be rebuilt from a file alone
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".archives"}
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".opus", ".ogg")
ID3_EXTS = (".mp3", ".wav")


@dataclass
class RetagResult:
    changed: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)


def _retag_id3(path: Path, mode: str) -> bool:
    if path.suffix.lower() == ".wav":
        audio = WAVE(path)
        tags, save = audio.tags, audio.save
        if tags is None:
            return False
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            return False
        save = lambda: tags.save(path)  # noqa: E731
    before = {key: str(tags.get(key, "")) for key in ("TALB", "TPE2", "TRCK")}
    if mode == "title":
        title = str(tags.get("TIT2", "")) or path.stem
        tags.setall("TALB", [TALB(encoding=3, text=title)])
        tags.delall("TPE2")  # album artist + track number belonged to the playlist-album
        tags.delall("TRCK")
    else:
        for key in ("TALB", "TPE2", "TRCK"):
            tags.delall(key)
    after = {key: str(tags.get(key, "")) for key in ("TALB", "TPE2", "TRCK")}
    if after == before:
        return False
    save()
    return True


def _retag_easy(path: Path, mode: str) -> bool:
    """M4A, FLAC, Opus, Ogg: mutagen's common 'album' / 'albumartist' / 'tracknumber' names."""
    audio = mutagen.File(path, easy=True)
    if audio is None or audio.tags is None:
        return False
    keys = ("album", "albumartist", "tracknumber")
    before = {key: audio.get(key) for key in keys}
    for key in keys:
        if key in audio:
            del audio[key]
    if mode == "title":
        audio["album"] = (audio.get("title") or [path.stem])[0]
    if {key: audio.get(key) for key in keys} == before:
        return False
    audio.save()
    return True


def retag_file(path: Path, mode: str) -> bool:
    """Apply `mode` to one song. Returns True if its tags changed."""
    if mode not in RETAG_MODES:
        raise ValueError(f"can't retag with mode {mode!r}")
    if path.suffix.lower() in ID3_EXTS:
        return _retag_id3(path, mode)
    return _retag_easy(path, mode)


def song_files(root: Path):
    for folder, dirs, files in os.walk(root, onerror=lambda _err: None):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            lowered = name.lower()
            if lowered.endswith(AUDIO_EXTS) and ".temp." not in lowered:
                yield Path(folder) / name


def retag_library(root: Path, mode: str, progress: Callable[[int], None] | None = None) -> RetagResult:
    if mode not in RETAG_MODES:
        raise ValueError(f"can't retag with mode {mode!r}")
    result = RetagResult()
    for count, path in enumerate(song_files(root), 1):
        try:
            if retag_file(path, mode):
                result.changed += 1
            else:
                result.unchanged += 1
        except Exception as err:  # a file being written or locked shouldn't stop the rest
            result.failed.append(f"{path.name}: {err}")
        if progress and count % 25 == 0:
            progress(count)
    return result
