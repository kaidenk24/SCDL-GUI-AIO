"""Rewrite the Album tags of MP3s already in the library to match the album setting. Tags only -
the audio is never touched. No Qt in here."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.id3 import ID3, TALB, ID3NoHeaderError

RETAG_MODES = ("title", "none")  # "playlist" can't be rebuilt from a file alone
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".archives"}


@dataclass
class RetagResult:
    changed: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)


def retag_file(path: Path, mode: str) -> bool:
    """Apply `mode` to one MP3. Returns True if its tags changed."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return False
    before = {key: str(tags.get(key, "")) for key in ("TALB", "TPE2", "TRCK")}
    if mode == "title":
        title = str(tags.get("TIT2", "")) or path.stem
        tags.setall("TALB", [TALB(encoding=3, text=title)])
        tags.delall("TPE2")  # album artist + track number belonged to the playlist-album
        tags.delall("TRCK")
    elif mode == "none":
        for key in ("TALB", "TPE2", "TRCK"):
            tags.delall(key)
    else:
        raise ValueError(f"can't retag with mode {mode!r}")
    after = {key: str(tags.get(key, "")) for key in ("TALB", "TPE2", "TRCK")}
    if after == before:
        return False
    tags.save(path)
    return True


def mp3_files(root: Path):
    for folder, dirs, files in os.walk(root, onerror=lambda _err: None):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.lower().endswith(".mp3") and not name.lower().endswith(".temp.mp3"):
                yield Path(folder) / name


def retag_library(root: Path, mode: str, progress: Callable[[int], None] | None = None) -> RetagResult:
    if mode not in RETAG_MODES:
        raise ValueError(f"can't retag with mode {mode!r}")
    result = RetagResult()
    for count, path in enumerate(mp3_files(root), 1):
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
