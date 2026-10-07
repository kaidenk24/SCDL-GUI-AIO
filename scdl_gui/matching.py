"""Finding a DRM-protected SoundCloud track on YouTube: search queries and match scoring. No I/O."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

STRONG_MATCH = 90  # score the "accept all strong matches" button trusts

# Bracketed bits that aren't part of the song's name.
_NOISE_BRACKETS = re.compile(
    r"[\(\[\{][^\)\]\}]*?(free\s*(d(own)?l(oad)?|dl)|out\s*now|official|premiere|exclusive|\bhq\b|\bhd\b|"
    r"music\s*video|audio|lyrics?|visuali[sz]er|buy|link\s*in|support)[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_NOISE_TAIL = re.compile(r"\s*[|｜/]\s*(free\s*download|out\s*now|buy|support).*$", re.IGNORECASE)
_FEAT = re.compile(r"\s*[\(\[]?\b(feat\.?|ft\.?|featuring|with)\s+[^\)\]]*[\)\]]?", re.IGNORECASE)
_SPLIT_ARTIST = re.compile(r"\s+[-–—]\s+")
# Different recordings of the same song: penalise when only one side mentions them.
VERSION_WORDS = (
    "remix", "live", "cover", "karaoke", "instrumental", "acoustic", "slowed", "sped up", "reverb",
    "nightcore", "8d", "bootleg", "flip", "mashup", "vip", "extended", "acapella", "edit", "rework",
)


@dataclass(frozen=True)
class Candidate:
    id: str
    url: str
    title: str
    channel: str = ""
    duration: int | None = None
    source: str = "YouTube"  # "YouTube Music" or "YouTube"
    score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_title(title: str) -> str:
    title = _NOISE_TAIL.sub("", title or "")
    title = _NOISE_BRACKETS.sub("", title)
    return re.sub(r"\s+", " ", title).strip(" -")


def song_and_artist(track: dict) -> tuple[str, str]:
    """Best guess at (song name, artist) for a SoundCloud track record."""
    title = clean_title(track.get("title", ""))
    artist = (track.get("artist") or "").strip()
    parts = _SPLIT_ARTIST.split(title, maxsplit=1)
    if len(parts) == 2 and (not artist or normalize(parts[0]) in normalize(artist) or normalize(artist) in normalize(parts[0])):
        return parts[1].strip(), artist or parts[0].strip()
    return title, artist or (track.get("uploader") or "").strip()


def build_query(track: dict) -> str:
    song, artist = song_and_artist(track)
    song = _FEAT.sub("", song).strip() or song
    if artist and normalize(artist) not in normalize(song):
        return f"{artist} {song}"
    return song


def _token_overlap(a: str, b: str) -> float:
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def similarity(a: str, b: str) -> float:
    """0..1, tolerant of word order and extra words on either side."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    return max(SequenceMatcher(None, na, nb).ratio(), _token_overlap(na, nb) * 0.95)


def _duration_points(source: int | None, candidate: int | None) -> float:
    if not source or not candidate:
        return 8
    diff = abs(source - candidate)
    for limit, points in ((2, 30), (5, 22), (10, 10), (20, 0)):
        if diff <= limit:
            return points
    return -25


def score(track: dict, candidate: Candidate) -> int:
    """0..100 confidence that the candidate is the same recording as the SoundCloud track."""
    song, artist = song_and_artist(track)
    source_text = normalize(f"{track.get('title', '')}")
    cand_title = clean_title(candidate.title)
    cand_text = normalize(f"{cand_title} {candidate.channel}")

    title_sim = max(similarity(song, cand_title), similarity(f"{artist} {song}", cand_title))
    points = 45 * title_sim
    artist_tokens = set(normalize(artist).split())
    if artist_tokens:
        found = artist_tokens & set(cand_text.split())
        points += 20 if found == artist_tokens else 10 if found else -15  # same name, other artist
    points += _duration_points(track.get("duration"), candidate.duration)
    for word in VERSION_WORDS:
        in_source = re.search(rf"\b{word}\b", source_text) is not None
        in_candidate = re.search(rf"\b{word}\b", normalize(cand_title)) is not None
        if in_candidate and not in_source:
            points -= 20
        elif in_source and not in_candidate:
            points -= 10
    if candidate.source == "YouTube Music" or candidate.channel.endswith(" - Topic"):
        points += 5
    return max(0, min(100, round(points)))


def rank(track: dict, candidates: list[Candidate]) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for cand in candidates:
        scored = Candidate(**{**cand.to_dict(), "score": score(track, cand)})
        if cand.id not in unique or scored.score > unique[cand.id].score:
            unique[cand.id] = scored
    return sorted(unique.values(), key=lambda c: c.score, reverse=True)


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "?"
    return f"{seconds // 60}:{seconds % 60:02d}"
