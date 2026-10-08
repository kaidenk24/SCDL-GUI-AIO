"""DRM-protected tracks waiting for (or done with) a YouTube match, persisted between sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from scdl_gui.settings import _read_json, _write_json, data_dir

# Item states
SEARCHING = "searching"
REVIEW = "review"  # candidates found, waiting for the user
NO_MATCH = "no_match"
DOWNLOADING = "downloading"
SAVED = "saved"
SKIPPED = "skipped"
FAILED = "failed"

STATUS_TEXT = {
    SEARCHING: "Searching YouTube...",
    REVIEW: "Pick a match",
    NO_MATCH: "No match found",
    DOWNLOADING: "Downloading...",
    SAVED: "Saved",
    SKIPPED: "Skipped",
    FAILED: "Download failed",
}
OPEN_STATES = (SEARCHING, REVIEW, NO_MATCH, DOWNLOADING, FAILED)
NEEDS_USER = (REVIEW, NO_MATCH, FAILED)


@dataclass
class MatchItem:
    track: dict  # the worker's @@DRM record
    status: str = SEARCHING
    query: str = ""
    candidates: list[dict] = field(default_factory=list)
    chosen_url: str = ""
    message: str = ""

    @property
    def key(self) -> str:
        return item_key(self.track)

    @property
    def label(self) -> str:
        uploader = self.track.get("uploader") or ""
        return f"{self.track.get('title', '?')}" + (f"  -  {uploader}" if uploader else "")


def item_key(track: dict) -> str:
    """Same SoundCloud track going to the same file = same item."""
    return f"{track.get('sc_id', '')}|{track.get('target', '')}"


def load_matches() -> list[MatchItem]:
    raw = _read_json(data_dir() / "matches.json")
    items = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("track"), dict):
            continue
        item = MatchItem(
            track=entry["track"], status=entry.get("status", REVIEW), query=entry.get("query", ""),
            candidates=list(entry.get("candidates") or []), chosen_url=entry.get("chosen_url", ""),
            message=entry.get("message", ""),
        )
        if item.status in (SEARCHING, DOWNLOADING):  # interrupted: search again / let the user retry
            item.status = SEARCHING if item.status == SEARCHING else FAILED
        items.append(item)
    return items


def save_matches(items: list[MatchItem]) -> None:
    _write_json(data_dir() / "matches.json", [asdict(item) for item in items])


def load_skipped() -> set[str]:
    """Keys of tracks you skipped. Scheduled checks of followed playlists don't ask about them again
    (a download you start yourself still does)."""
    raw = _read_json(data_dir() / "matches-skipped.json")
    return {key for key in raw if isinstance(key, str)} if isinstance(raw, list) else set()


def save_skipped(keys: set[str]) -> None:
    _write_json(data_dir() / "matches-skipped.json", sorted(keys))
