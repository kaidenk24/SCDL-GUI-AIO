"""Tests for the Album tag setting: migration, download arguments, and retagging existing MP3s."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.id3 import ID3, TALB, TIT2, TPE2, TRCK

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import engine, retag, settings as settings_mod  # noqa: E402
from scdl_gui.settings import Job, Settings  # noqa: E402


def make_mp3(path: Path, title: str, album: str = "future/melodic") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TPE2(encoding=3, text="djexample"))
    tags.add(TRCK(encoding=3, text="007"))
    tags.save(path)
    return path


def album_of(path: Path) -> tuple[str, str, str]:
    tags = ID3(path)
    return str(tags.get("TALB", "")), str(tags.get("TPE2", "")), str(tags.get("TRCK", ""))


class SettingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def load_with(self, raw: dict) -> Settings:
        (settings_mod.data_dir() / "settings.json").write_text(json.dumps(raw), encoding="utf-8")
        return settings_mod.load_settings()

    def test_new_users_get_song_title_albums(self):
        self.assertEqual(settings_mod.load_settings().album_mode, "title")

    def test_old_settings_keep_their_behaviour(self):
        self.assertEqual(self.load_with({"album_tags": True}).album_mode, "playlist")
        self.assertEqual(self.load_with({"album_tags": False}).album_mode, "none")
        self.assertEqual(self.load_with({"album_tags": True, "album_mode": "title"}).album_mode, "title")

    def test_unknown_mode_falls_back(self):
        self.assertEqual(self.load_with({"album_mode": "bogus"}).album_mode, "title")

    def test_download_arguments(self):
        job = Job(url="https://soundcloud.com/a/sets/b")
        with tempfile.TemporaryDirectory() as library:
            for mode, scdl_album_tags in (("title", False), ("none", False), ("playlist", True)):
                args = engine.worker_args(Settings(library=library, album_mode=mode), job)
                self.assertEqual("--no-album-tag" not in args, scdl_album_tags, mode)
                self.assertEqual(engine.worker_env(Settings(library=library, album_mode=mode))["SCDL_ALBUM_MODE"], mode)


class RetagTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_title_mode(self):
        song = make_mp3(self.root / "future⧸melodic" / "IYKO - Let Go.mp3", "IYKO - Let Go")
        self.assertTrue(retag.retag_file(song, "title"))
        self.assertEqual(album_of(song), ("IYKO - Let Go", "", ""))
        self.assertFalse(retag.retag_file(song, "title"))  # already right: file not rewritten

    def test_none_mode(self):
        song = make_mp3(self.root / "a.mp3", "A")
        self.assertTrue(retag.retag_file(song, "none"))
        self.assertEqual(album_of(song), ("", "", ""))

    def test_playlist_mode_is_refused(self):
        with self.assertRaises(ValueError):
            retag.retag_library(self.root, "playlist")

    def test_library_walk_skips_system_and_archive_folders(self):
        make_mp3(self.root / "playlist one" / "a.mp3", "A")
        make_mp3(self.root / "b.mp3", "B")
        make_mp3(self.root / ".archives" / "c.mp3", "C")
        make_mp3(self.root / "$RECYCLE.BIN" / "d.mp3", "D")
        (self.root / "notes.txt").write_text("x")
        (self.root / "broken.mp3").write_bytes(b"not an mp3")  # no tags: counted as unchanged
        result = retag.retag_library(self.root, "title")
        self.assertEqual((result.changed, result.unchanged, result.failed), (2, 1, []))
        self.assertEqual(album_of(self.root / ".archives" / "c.mp3")[0], "future/melodic")

    def playlist_entry(self) -> dict:
        # What yt-dlp itself reports for a track from a SoundCloud playlist (seen in a real run).
        return {"title": "IYKO - Let Go", "album": "future/melodic", "album_artist": "djexample",
                "album_artists": ["djexample"], "album_type": "playlist", "meta_album": "future/melodic",
                "meta_track": "007"}

    def test_worker_title_mode_overrides_yt_dlp_album_fields(self):
        from scdl_gui import worker

        _files, out = worker.AlbumModePP("title").run(self.playlist_entry())
        self.assertEqual(out["meta_album"], "IYKO - Let Go")
        self.assertTrue(all(out[k] is None for k in ("album", "album_artist", "album_artists", "meta_album_artist", "meta_track")))

    def test_worker_download_setup_includes_the_album_step(self):
        # Runs scdl's real option building through the app's hook (a missing name here once broke every download).
        import scdl.scdl as scdl_main
        from docopt import docopt

        from scdl_gui import worker

        parsed = docopt(scdl_main.__doc__, argv=["-l", "https://soundcloud.com/a/sets/b", "--no-album-tag"])
        scdl_args = {key.strip("-").replace("-", "_"): value for key, value in parsed.items()}
        scdl_args.update(path=self.root, name_format="%(title)s.%(ext)s", playlist_name_format="%(title)s.%(ext)s",
                         client_id=None, auth_token=None)
        url = scdl_args.pop("l")
        with mock.patch.object(worker, "ALBUM_MODE", "title"):
            _url, params, postprocessors = worker.build_params(url, scdl_args)
        self.assertTrue(any(isinstance(pp, worker.AlbumModePP) for pp, _when in postprocessors))
        self.assertEqual(params["final_ext"], "mp3")

    def test_worker_none_mode_clears_everything(self):
        from scdl_gui import worker

        _files, out = worker.AlbumModePP("none").run(self.playlist_entry())
        self.assertTrue(all(out[k] is None for k in ("album", "album_artist", "album_artists", "meta_album", "meta_track")))


if __name__ == "__main__":
    unittest.main()
