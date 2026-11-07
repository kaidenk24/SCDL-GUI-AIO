"""Followed playlists: links the app checks on a schedule, downloading new tracks into their folder.

A check is an ordinary download of the link. The download archive (or the files already on disk) makes
it skip everything you already have, so only tracks added since the last check are downloaded.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, replace

from scdl_gui.engine import SINGLE_KINDS, guess_kind
from scdl_gui.parsing import JobCounts
from scdl_gui.settings import FOLDER_AUTO, Job, _coerce, _read_json, _write_json, data_dir

FILE_NAME = "followed.json"
RETRY_AFTER_FAILURE = 15 * 60.0  # a failed check (offline, drive asleep...) is retried this soon
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Watch:
    url: str
    folder: str | None = FOLDER_AUTO
    name: str = ""
    kind: str = ""
    enabled: bool = True
    last_checked: float = 0.0  # epoch seconds of the last finished check, 0 = never
    retry_at: float = 0.0  # set after a failed check: try again then instead of a full interval later
    last_result: str = ""  # e.g. "2 new tracks", "Up to date"
    last_new: float = 0.0  # epoch seconds when new tracks last arrived
    total_new: int = 0  # tracks downloaded by checks since following

    def with_changes(self, **changes) -> Watch:
        return replace(self, **changes)

    def as_job(self) -> Job:
        return Job(url=self.url, folder=self.folder, name=self.name, kind=self.kind)


def is_followable(url: str, kind: str = "") -> bool:
    """Anything that can gain tracks; a single track never changes."""
    return (kind or guess_kind(url)) not in SINGLE_KINDS


def describe_interval(hours: int) -> str:
    """'hour', '3 hours', 'day' (as in 'every ...')."""
    return "day" if hours == 24 else "hour" if hours == 1 else f"{hours} hours"


def due_at(watch: Watch, now: float, interval_hours: int) -> float:
    """When this watch should next be checked."""
    interval = max(int(interval_hours), 1) * 3600.0
    due = watch.retry_at or watch.last_checked + interval
    return now if due > now + interval else due  # the clock was turned back: don't wait for it to catch up


def is_due(watch: Watch, now: float, interval_hours: int) -> bool:
    return watch.enabled and now >= due_at(watch, now, interval_hours)


def next_check_at(watches: list[Watch], interval_hours: int, now: float) -> float | None:
    """When the next followed link is due, or None if nothing is followed."""
    times = [due_at(w, now, interval_hours) for w in watches if w.enabled]
    return min(times) if times else None


def add_watches(watches: list[Watch], urls: list[str], folder: str | None) -> tuple[list[Watch], list[str]]:
    """(new list, links that were added); links already followed, and single tracks, are left out."""
    known = {w.url for w in watches}
    fresh = [u for u in dict.fromkeys(urls) if u not in known and is_followable(u)]
    return [*watches, *(Watch(url=u, folder=folder) for u in fresh)], fresh


def result_text(status: str, counts: JobCounts) -> str:
    """Short outcome of one check for the Playlists page."""
    if status.startswith("Failed"):
        return status
    parts = []
    if counts.saved:
        parts.append(f"{counts.saved} new track{'s' if counts.saved != 1 else ''}")
    if counts.to_match:
        parts.append(f"{counts.to_match} to match on YouTube")
    if counts.failed:
        parts.append(f"{counts.failed} failed")
    return ", ".join(parts) if parts else "Up to date"


def record_check(watch: Watch, now: float, status: str, counts: JobCounts) -> Watch:
    """The watch after a finished check (stopped checks aren't recorded, so they run again). A failed
    check keeps the last good check time and is retried in RETRY_AFTER_FAILURE."""
    if status.startswith("Failed"):
        return watch.with_changes(last_result=result_text(status, counts), retry_at=now + RETRY_AFTER_FAILURE)
    changes: dict = {"last_checked": now, "retry_at": 0.0, "last_result": result_text(status, counts)}
    if counts.saved:
        changes.update(last_new=now, total_new=watch.total_new + counts.saved)
    return watch.with_changes(**changes)


def load_watches() -> list[Watch]:
    path = data_dir() / FILE_NAME
    raw = _read_json(path)
    if raw is None and path.exists():  # unreadable: keep a copy rather than overwrite it on the next save
        try:
            os.replace(path, path.with_suffix(".json.bad"))
            log.warning("Kept the unreadable %s as %s", path.name, path.with_suffix(".json.bad").name)
        except OSError as err:
            log.warning("Couldn't set aside %s: %s", path, err)
    watches: dict[str, Watch] = {}
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("url"), str) and entry["url"] not in watches:
            watch = _coerce(Watch, entry)  # values of the wrong type fall back to defaults
            if watch.folder is not None and not isinstance(watch.folder, str):
                watch = watch.with_changes(folder=FOLDER_AUTO)
            watches[watch.url] = watch
    return list(watches.values())


def save_watches(watches: list[Watch]) -> None:
    _write_json(data_dir() / FILE_NAME, [asdict(w) for w in watches])


def describe_age(then: float, now: float) -> str:
    """'Never', 'Just now', '5 min ago', '3 h ago', '2 days ago'."""
    if not then:
        return "Never"
    seconds = max(now - then, 0)
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def describe_wait(seconds: float) -> str:
    """'now', 'in 5 min', 'in 2 h 14 min'."""
    if seconds < 60:
        return "now"
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"in {minutes} min"
    return f"in {hours} h {minutes} min" if minutes else f"in {hours} h"
