"""Tests for the DRM -> YouTube matching logic. Run: python -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import engine, matches  # noqa: E402
from scdl_gui.matching import Candidate, build_query, clean_title, rank, score, song_and_artist  # noqa: E402
from scdl_gui.parsing import JobCounts, OutputParser  # noqa: E402
from scdl_gui.settings import Settings  # noqa: E402

TRACK = {"title": "Neon Skyline!", "uploader": "Aurora Vale", "artist": "Aurora Vale", "duration": 151, "isrc": "XX0000000001"}

# Shaped like real search results: official upload, re-upload, same name by another artist, extended mix, DJ set.
RESULTS = [
    Candidate("CtgqavhpzvE", "https://youtu.be/1", "Neon Skyline!", "Aurora Vale - Topic", 151, "YouTube"),
    Candidate("nFiKK4YueVk", "https://youtu.be/2", "Aurora Vale - Neon Skyline!", "Label Uploads", 151, "YouTube"),
    Candidate("B4NsWcSrOjc", "https://youtu.be/3", "Neon Skyline", "Somebody Else", 150, "YouTube Music"),
    Candidate("MOS9gcFt4Zc", "https://youtu.be/4", "Neon Skyline! (Extended Mix)", "Aurora Vale - Topic", 210, "YouTube"),
    Candidate("qB0PPjslqIE", "https://youtu.be/5", "Weekend house DJ set", "Mix Channel", 1660, "YouTube"),
]


class QueryTests(unittest.TestCase):
    def test_clean_title_drops_promo_brackets(self):
        self.assertEqual(clean_title("Song (Official Video) [FREE DOWNLOAD]"), "Song")
        self.assertEqual(clean_title("Track | Free Download"), "Track")
        self.assertEqual(clean_title("Levels (VIP Remix)"), "Levels (VIP Remix)")

    def test_song_and_artist_from_dash_title(self):
        self.assertEqual(song_and_artist({"title": "Aurora Vale - Golden Hour", "uploader": "auroravale"}), ("Golden Hour", "Aurora Vale"))

    def test_publisher_artist_wins_over_uploader(self):
        self.assertEqual(song_and_artist({"title": "Midnight", "uploader": "Big Label", "artist": "Nova"}), ("Midnight", "Nova"))

    def test_build_query(self):
        self.assertEqual(build_query(TRACK), "Aurora Vale Neon Skyline!")
        self.assertEqual(build_query({"title": "Starlight (feat. Someone)", "artist": "Nova"}), "Nova Starlight")


class ScoringTests(unittest.TestCase):
    def test_official_upload_ranks_first_and_strong(self):
        ranked = rank(TRACK, RESULTS)
        self.assertEqual(ranked[0].id, "CtgqavhpzvE")
        self.assertGreaterEqual(ranked[0].score, 90)

    def test_same_name_by_other_artist_is_not_strong(self):
        self.assertLess(score(TRACK, RESULTS[2]), 70)

    def test_different_version_is_weak(self):
        self.assertLess(score(TRACK, RESULTS[3]), 50)
        self.assertLess(score(TRACK, RESULTS[4]), 20)

    def test_rank_dedupes_by_video(self):
        doubled = RESULTS + [Candidate("CtgqavhpzvE", "https://music.youtube.com/x", "Neon Skyline!", "Aurora Vale", 151, "YouTube Music")]
        ids = [c.id for c in rank(TRACK, doubled)]
        self.assertEqual(ids.count("CtgqavhpzvE"), 1)


class PlumbingTests(unittest.TestCase):
    def test_parser_drm_events(self):
        parser = OutputParser()
        error = parser.feed("ERROR: [soundcloud] 1632408063: This video is DRM protected")
        self.assertTrue(error.data["drm"])
        drm = parser.feed('@@DRM {"sc_id": "1", "title": "Neon Skyline!", "target": "E:\\\\x"}')
        self.assertEqual((drm.kind, drm.data["title"]), ("drm", "Neon Skyline!"))
        login = parser.feed('@@LOGIN {"soundcloud": true, "youtube": false}')
        self.assertEqual(login.data, {"soundcloud": True, "youtube": False})

    def test_counts_summary_mentions_matches(self):
        self.assertEqual(JobCounts(14, 0, 0, 1).summary(), "14 new, 1 to match on YouTube")

    def test_worker_env_youtube_settings(self):
        env = engine.worker_env(Settings(library="E:\\", youtube_fallback=False, youtube_po_token=" abc "))
        self.assertEqual((env["SCDL_YT_FALLBACK"], env["SCDL_YT_PO_TOKEN"]), ("0", "abc"))

    def test_matches_round_trip_and_interrupted_states(self):
        with tempfile.TemporaryDirectory() as appdata, mock.patch.dict(os.environ, {"APPDATA": appdata}):
            items = [
                matches.MatchItem(track={"sc_id": "1", "target": "a"}, status=matches.REVIEW, candidates=[{"score": 99}]),
                matches.MatchItem(track={"sc_id": "2", "target": "b"}, status=matches.DOWNLOADING),
                matches.MatchItem(track={"sc_id": "3", "target": "c"}, status=matches.SEARCHING),
            ]
            matches.save_matches(items)
            loaded = matches.load_matches()
            self.assertEqual([i.status for i in loaded], [matches.REVIEW, matches.FAILED, matches.SEARCHING])
            self.assertEqual(loaded[0].candidates, [{"score": 99}])
            self.assertEqual(loaded[0].key, "1|a")


if __name__ == "__main__":
    unittest.main()
