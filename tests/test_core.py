"""Unit tests for templates, link handling, worker arguments, output parsing and settings."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import engine, templates  # noqa: E402
from scdl_gui import settings as settings_mod
from scdl_gui.parsing import JobCounts, OutputParser, friendly_error  # noqa: E402
from scdl_gui.settings import FOLDER_ROOT, Job, Settings  # noqa: E402

LIBRARY = "D:\\Music"


class TemplateTests(unittest.TestCase):
    def test_title_only_is_plain(self):
        self.assertEqual(templates.to_ytdl("{title}"), "%(title)s")

    def test_index_stays_plain_for_zero_padding(self):
        self.assertEqual(templates.to_ytdl("{index} - {title}"), "%(playlist_index)s - %(title)s")

    def test_single_track_drops_playlist_tokens_and_separators(self):
        self.assertEqual(templates.to_ytdl("{index} - {title}", single_track=True), "%(title)s")
        self.assertEqual(templates.to_ytdl("{owner}\\{playlist}/{title}", single_track=True), "//%(title)s")

    def test_optional_token_separator_is_conditional(self):
        self.assertEqual(templates.to_ytdl("{genre} - {title}"), "%(genre&{} - |)s%(title)s")

    def test_literal_percent_is_escaped_and_unknown_tokens_kept(self):
        self.assertEqual(templates.to_ytdl("100% {bogus}"), "100%% {bogus}")
        self.assertEqual(templates.unknown_tokens("{title} {bogus}"), ["bogus"])

    def test_output_target_relative_layout(self):
        target = templates.output_target(LIBRARY, "{playlist}", "{title}")
        self.assertEqual(target.base, LIBRARY)
        self.assertEqual(target.playlist_format, "%(playlist)s/%(title)s.%(ext)s")
        self.assertEqual(target.single_format, "%(title)s.%(ext)s")

    def test_output_target_absolute_layout_with_token(self):
        target = templates.output_target(LIBRARY, "E:\\Car\\{playlist}", "{title}")
        self.assertEqual(target.base, "E:\\Car")
        self.assertEqual(target.playlist_format, "%(playlist)s/%(title)s.%(ext)s")

    def test_output_target_never_starts_with_separator(self):
        target = templates.output_target(LIBRARY, "{owner}\\{playlist}", "{index} - {title}")
        self.assertEqual(target.single_format, "%(title)s.%(ext)s")
        self.assertEqual(target.playlist_format, "%(playlist_uploader)s/%(playlist)s/%(playlist_index)s - %(title)s.%(ext)s")

    def test_output_target_drive_root(self):
        self.assertEqual(templates.output_target(LIBRARY, "E:\\", "{title}").base, "E:\\")

    def test_clean_folder_name(self):
        self.assertEqual(templates.clean_folder_name(' Gym/Warm-up?* '), "Gym\\Warm-up")
        self.assertEqual(templates.clean_folder_name("E:\\Music\\"), "E:\\Music")
        self.assertEqual(templates.clean_folder_name("E:\\"), "E:\\")

    def test_preview_paths(self):
        rows = dict(templates.preview_paths(LIBRARY, "{playlist}", "{index} - {title}"))
        self.assertEqual(rows["Playlist track"], "D:\\Music\\Summer House\\07 - Summer Nights (VIP Mix).mp3")
        self.assertEqual(rows["Liked track"], "D:\\Music\\djexample (Likes)\\003 - Golden Hour.mp3")
        self.assertEqual(rows["Single track link"], "D:\\Music\\Night Drive.mp3")


class EngineTests(unittest.TestCase):
    def test_extract_links_cleans_and_dedupes(self):
        text = (
            "check https://soundcloud.com/djexample/sets/summer?si=abc&utm_source=x and\n"
            "# https://soundcloud.com/ignored/comment\n"
            "https://soundcloud.com/djexample/sets/summer/ https://on.soundcloud.com/AbC123"
        )
        self.assertEqual(
            engine.extract_links(text),
            ["https://soundcloud.com/djexample/sets/summer", "https://on.soundcloud.com/AbC123"],
        )

    def test_guess_kind(self):
        cases = {
            "https://soundcloud.com/djexample/sets/summer": "Playlist",
            "https://soundcloud.com/djexample/likes": "Likes",
            "https://soundcloud.com/djexample/sets": "All playlists",
            "https://soundcloud.com/djexample": "Profile",
            "https://soundcloud.com/djexample/some-track": "Track",
            "https://soundcloud.com/stations/track/a/b": "Station",
            "https://on.soundcloud.com/x": "Share link",
        }
        for url, kind in cases.items():
            self.assertEqual(engine.guess_kind(url), kind, url)

    def test_worker_args_custom_folder_per_link_archive(self):
        with tempfile.TemporaryDirectory() as library:
            s = Settings(library=library, archive_mode="per_link", full_art=False, use_originals=False)
            job = Job(url="https://soundcloud.com/djexample/sets/summer", folder="Gym\\{playlist}")
            args = engine.worker_args(s, job)
            self.assertIn("--no-original", args)
            self.assertNotIn("--original-art", args)
            self.assertEqual(args[args.index("--playlist-name-format") + 1], "Gym/%(playlist)s/%(title)s.%(ext)s")
            archive = Path(args[args.index("--download-archive") + 1])
            self.assertEqual(archive.name, "djexample_sets_summer.txt")
            self.assertTrue(archive.parent.is_dir())

    def test_worker_args_root_folder_and_file_check_mode(self):
        s = Settings(library=LIBRARY, archive_mode="files")
        args = engine.worker_args(s, Job(url="https://soundcloud.com/a/b", folder=FOLDER_ROOT))
        self.assertIn("-c", args)
        self.assertNotIn("--download-archive", args)
        self.assertEqual(args[args.index("--playlist-name-format") + 1], "%(title)s.%(ext)s")

    def test_firefox_profiles_reads_utf16_and_utf8(self):
        ini = "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abc.default-release\n"
        for encoded in (ini.encode("utf-16"), ini.encode("utf-8-sig"), ini.encode("utf-8")):
            with tempfile.TemporaryDirectory() as appdata, mock.patch.dict(os.environ, {"APPDATA": appdata}):
                root = Path(appdata) / "Mozilla" / "Firefox"
                profile = root / "Profiles" / "abc.default-release"
                profile.mkdir(parents=True)
                (profile / "cookies.sqlite").write_bytes(b"")
                (root / "profiles.ini").write_bytes(encoded)
                self.assertEqual(engine.firefox_profiles(), [("default-release", str(profile))])

    def test_worker_env(self):
        with mock.patch.object(engine, "find_js_runtime", return_value=None), \
                mock.patch.object(engine, "find_ffmpeg", return_value="C:\\ff\\ffmpeg.exe"):
            env = engine.worker_env(Settings(library=LIBRARY, normalize=False, use_login=False, quality="320",
                                             cookie_browser="edge"))
        self.assertEqual(env["SCDL_TARGET_LUFS"], "")
        self.assertEqual((env["SCDL_BROWSER"], env["SCDL_SC_LOGIN"]), ("edge", "0"))
        self.assertEqual(env["SCDL_MP3_QUALITY"], "320")
        self.assertEqual(env["SCDL_FFMPEG"], "C:\\ff\\ffmpeg.exe")
        self.assertEqual(env["SCDL_JS_RUNTIME"], "")
        self.assertEqual(engine.worker_env(Settings(library=LIBRARY, target_lufs=-11.5))["SCDL_TARGET_LUFS"], "-11.5")

    def test_js_runtime_spec(self):
        with mock.patch.object(engine, "find_js_runtime", return_value="C:\\Program Files\\nodejs\\node.exe"):
            self.assertEqual(engine.js_runtime_spec(), "node:C:\\Program Files\\nodejs\\node.exe")
        with mock.patch.object(engine, "find_js_runtime", return_value="C:\\Users\\x\\.deno\\bin\\deno.exe"):
            self.assertTrue(engine.js_runtime_spec().startswith("deno:"))

    def test_find_ffmpeg_prefers_setting_and_falls_back_to_winget(self):
        with tempfile.TemporaryDirectory() as local:
            exe = Path(local) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "bin" / "ffmpeg.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": local}), mock.patch("shutil.which", return_value=None):
                self.assertEqual(engine.find_ffmpeg(Settings()), str(exe))
                self.assertIsNone(engine.find_ffmpeg(Settings(ffmpeg_path="Z:\\missing\\ffmpeg.exe")))


class ParsingTests(unittest.TestCase):
    def test_events(self):
        parser = OutputParser()
        self.assertEqual(parser.feed("[download] Downloading item 4 of 15").current, 4)
        self.assertEqual(parser.feed("[download] Downloading playlist: Summer House").text, "Summer House")
        saved = parser.feed('[Mutagen] Adding metadata to "D:\\Music\\Summer House\\Golden Hour.mp3"')
        self.assertEqual((saved.kind, saved.text), ("saved", "Golden Hour"))
        skipped = parser.feed("[download] 1566458017: Night Drive has already been recorded in the archive")
        self.assertEqual((skipped.kind, skipped.text), ("skipped", "Night Drive"))
        self.assertIsNone(parser.feed("[soundcloud] Extracting URL: https://soundcloud.com/dj/locked-track"))
        error = parser.feed("ERROR: [soundcloud] 1632408063: This video is DRM protected")
        self.assertEqual(error.kind, "error")
        self.assertEqual(error.data["track"], "dj/locked-track")
        self.assertIn("DRM", error.text)

    def test_describe_line(self):
        event = OutputParser().feed('@@DESCRIBE {"url": "u", "title": "Summer House", "kind": "Playlist"}')
        self.assertEqual(event.data["title"], "Summer House")

    def test_friendly_error_fallback(self):
        self.assertEqual(friendly_error("something odd "), "something odd")

    def test_counts_summary(self):
        self.assertEqual(JobCounts(3, 1, 2).summary(), "3 new, 1 already had, 2 failed")
        self.assertEqual(JobCounts(5).summary(), "5 new")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_round_trip(self):
        original = Settings(library=LIBRARY, folders=("Gym", "E:\\Car"), target_lufs=-11.0, new_link_folder="Gym")
        settings_mod.save_settings(original)
        self.assertEqual(settings_mod.load_settings(), original)

    def test_default_library_is_in_the_users_music_folder(self):
        self.assertEqual(settings_mod.load_settings().library, str(Path.home() / "Music" / "SoundCloud"))

    def test_bad_values_fall_back_to_defaults(self):
        path = settings_mod.data_dir() / "settings.json"
        bad = {"quality": "999", "target_lufs": 3, "normalize": "yes", "cookie_browser": "netscape", "nope": 1}
        path.write_text(json.dumps(bad), encoding="utf-8")
        loaded = settings_mod.load_settings()
        self.assertEqual((loaded.quality, loaded.target_lufs, loaded.cookie_browser), ("V0", -14.0, "firefox"))
        self.assertTrue(loaded.normalize)

    def test_corrupt_file_is_ignored(self):
        (settings_mod.data_dir() / "settings.json").write_text("{not json", encoding="utf-8")
        with self.assertLogs("scdl_gui.settings", level="WARNING"):
            self.assertEqual(settings_mod.load_settings().quality, "V0")

    def test_queue_round_trip_resets_interrupted_status(self):
        settings_mod.save_queue([Job(url="u1", status="Downloading 3 of 9"), Job(url="u2", status="Done - 4 new", folder=None)])
        jobs = settings_mod.load_queue()
        self.assertEqual([j.status for j in jobs], ["Queued", "Done - 4 new"])


if __name__ == "__main__":
    unittest.main()
