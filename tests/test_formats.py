"""Output formats and YouTube links: settings, worker arguments, the YouTube download setup and tags."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import engine, formats  # noqa: E402
from scdl_gui import settings as settings_mod
from scdl_gui.parsing import OutputParser  # noqa: E402
from scdl_gui.settings import Job, Settings  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_encoders(self):
        mp3, m4a, opus = (formats.audio_format(k) for k in ("mp3", "m4a", "opus"))
        self.assertEqual(formats.encoder_args(mp3, "V0", 256), ["-c:a", "libmp3lame", "-q:a", "0"])
        self.assertEqual(formats.encoder_args(mp3, "320", 256), ["-c:a", "libmp3lame", "-b:a", "320k"])
        self.assertEqual(formats.encoder_args(m4a, "V0", 256), ["-c:a", "aac", "-b:a", "256k"])
        self.assertEqual(formats.encoder_args(opus, "V0", 160), ["-c:a", "libopus", "-b:a", "160k"])
        self.assertEqual(formats.extract_quality(mp3, "V2", 0), "2")
        self.assertIsNone(formats.extract_quality(formats.audio_format("flac"), "V0", 256))
        with self.assertRaises(ValueError):
            formats.encoder_args(formats.audio_format("original"), "V0", 256)

    def test_no_reencode_when_the_source_already_fits(self):
        # Levelling off + AAC wanted: take the AAC stream so it's only repackaged, not re-encoded.
        m4a = formats.audio_format("m4a")
        self.assertEqual(formats.source_format(m4a, levelling=False), "bestaudio[acodec^=mp4a]/bestaudio/best")
        self.assertEqual(formats.source_format(m4a, levelling=True), "bestaudio/best")  # re-encoded anyway: best
        self.assertEqual(formats.source_format(formats.audio_format("mp3"), levelling=False), "bestaudio/best")

    def test_unknown_format_falls_back(self):
        self.assertEqual(formats.audio_format("aiff").key, "mp3")
        with tempfile.TemporaryDirectory() as appdata, mock.patch.dict(os.environ, {"APPDATA": appdata}):
            settings_mod.save_settings(Settings(library=appdata, audio_format="aiff", aac_bitrate=999))
            loaded = settings_mod.load_settings()
        self.assertEqual((loaded.audio_format, loaded.aac_bitrate), ("mp3", 256))

    def test_worker_gets_the_format(self):
        env = engine.worker_env(Settings(library="E:\\", audio_format="opus", opus_bitrate=128))
        self.assertEqual((env["SCDL_FORMAT"], env["SCDL_BITRATE"]), ("opus", "128"))
        env = engine.worker_env(Settings(library="E:\\", audio_format="m4a", aac_bitrate=320))
        self.assertEqual(env["SCDL_BITRATE"], "320")


class YouTubeLinkTests(unittest.TestCase):
    def test_links_are_found_and_cleaned(self):
        text = (
            "https://youtu.be/dQw4w9WgXcQ?si=abc  https://www.youtube.com/watch?v=abc&list=PLx&index=3\n"
            "https://music.youtube.com/playlist?list=OLAK5uy_x&si=1 https://m.youtube.com/@artist?x=1\n"
            "https://www.youtube.com/shorts/sh0rt?feature=share https://soundcloud.com/a/sets/b?si=zz\n"
            "https://www.youtube.com/watch?feature=x"  # no video: not a link to anything
        )
        self.assertEqual(engine.extract_links(text), [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=abc",  # a video opened from a playlist means that video
            "https://music.youtube.com/playlist?list=OLAK5uy_x",
            "https://www.youtube.com/@artist",
            "https://www.youtube.com/watch?v=sh0rt",
            "https://soundcloud.com/a/sets/b",
        ])

    def test_only_links_to_music_are_kept(self):
        text = (
            "(https://www.youtube.com/watch?v=abc). https://www.youtube.com/live/liv3 https://www.youtube.com/embed/emb "
            "https://www.youtube.com/results?search_query=x https://www.youtube.com/feed/history "
            "https://music.youtube.com/browse/MPREb_1 https://www.youtube.com/channel/UC1/releases"
        )
        self.assertEqual(engine.extract_links(text), [
            "https://www.youtube.com/watch?v=abc",
            "https://www.youtube.com/watch?v=liv3",
            "https://www.youtube.com/watch?v=emb",
            "https://music.youtube.com/browse/MPREb_1",
            "https://www.youtube.com/channel/UC1/releases",
        ])

    def test_kinds(self):
        kinds = [engine.guess_kind(u) for u in (
            "https://www.youtube.com/watch?v=a", "https://www.youtube.com/playlist?list=b", "https://www.youtube.com/@c")]
        self.assertEqual(kinds, ["YouTube video", "YouTube playlist", "YouTube channel"])
        from scdl_gui.watches import is_followable

        self.assertFalse(is_followable("https://www.youtube.com/watch?v=a"))
        self.assertTrue(is_followable("https://www.youtube.com/playlist?list=b"))

    def test_worker_args(self):
        with tempfile.TemporaryDirectory() as library:
            settings = Settings(library=library)
            youtube = engine.worker_args(settings, Job(url="https://www.youtube.com/playlist?list=PLx"))
            soundcloud = engine.worker_args(settings, Job(url="https://soundcloud.com/a/sets/b"))
        self.assertEqual(youtube[:3], ["--youtube", "-l", "https://www.youtube.com/playlist?list=PLx"])
        self.assertEqual(soundcloud[:2], ["-l", "https://soundcloud.com/a/sets/b"])
        self.assertIn("youtube_playlist_list_PLx", engine.link_slug("https://www.youtube.com/playlist?list=PLx"))

    def test_parser_reads_youtube_and_levelling_lines(self):
        parser = OutputParser()
        self.assertIsNone(parser.feed("[youtube] Extracting URL: https://www.youtube.com/watch?v=abc"))
        error = parser.feed("ERROR: [youtube] abc: Video unavailable")
        self.assertEqual(error.data["track"], "watch?v=abc")
        self.assertEqual(parser.feed("[Loudness] -9.1 LUFS -> -14 LUFS").kind, "loudness")
        self.assertEqual(parser.feed("[LoudnessMp3] -9.1 LUFS -> -14 LUFS").kind, "loudness")  # older workers


class YouTubeDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scdl_gui import youtube_links

        cls.links = youtube_links

    def args(self, *extra):
        return ["-l", "https://www.youtube.com/watch?v=a", "--path", "E:\\Music", "--name-format", "%(title)s.%(ext)s",
                "--playlist-name-format", "%(playlist)s/%(title)s.%(ext)s", "--original-art", "-c", *extra]

    def test_download_setup(self):
        opts = self.links.parse_args(self.args("--download-archive", "E:\\a.txt"))  # SoundCloud-only flags ignored
        with mock.patch.object(self.links.worker, "FORMAT", formats.audio_format("opus")), \
                mock.patch.object(self.links.worker, "TARGET_LUFS", None):
            params = self.links.build_params(opts, self.links.Output())
        self.assertEqual(params["format"], "bestaudio[acodec^=opus]/bestaudio/best")
        self.assertEqual(params["final_ext"], "opus")
        self.assertEqual(params["download_archive"], "E:\\a.txt")
        self.assertFalse(params["noplaylist"])

    def test_conversion_step(self):
        from scdl_gui import worker

        with mock.patch.object(worker, "TARGET_LUFS", None):
            self.assertIsInstance(worker.convert_pp(), worker.ConvertPP)
        with mock.patch.object(worker, "TARGET_LUFS", "-14"):
            self.assertIsInstance(worker.convert_pp(), worker.LoudnessPP)

    def test_a_file_already_in_the_folder_is_left_alone(self):
        # yt-dlp would re-encode an existing WAV (ffprobe says pcm_s16le, not wav) and drop its tags.
        from scdl_gui import worker

        with mock.patch.object(worker, "FORMAT", formats.audio_format("wav")):
            convert = worker.ConvertPP()
            existing = {"filepath": "E:\\x\\Song.wav", "ext": "wav", "__real_download": False}
            with mock.patch.object(worker.FFmpegExtractAudioPP, "run", side_effect=AssertionError("re-encoded")):
                self.assertEqual(convert.run(dict(existing)), ([], existing))

    def test_no_conversion_looks_for_the_file_it_would_make(self):
        # "No conversion" saves YouTube's Opus as .opus; without this yt-dlp looked for .webm and downloaded again.
        from scdl_gui import worker

        downloader = mock.Mock(params={}, _postprocessor_hooks=[])
        step = worker.ExistingFilePP(downloader)
        with mock.patch.object(worker, "FORMAT", formats.audio_format("original")):
            step.run({"acodec": "opus"})
            self.assertEqual(downloader.params["final_ext"], "opus")
            step.run({"acodec": "mp4a.40.2"})
            self.assertEqual(downloader.params["final_ext"], "m4a")

    def test_youtube_playlists_without_an_owner_still_use_the_playlist_layout(self):
        from scdl.patches.switch_outtmpl_preprocessor import OuttmplPP

        downloader = mock.Mock(params={"outtmpl": {"default": ""}}, _postprocessor_hooks=[])
        step = OuttmplPP("single.%(ext)s", "%(playlist)s/one.%(ext)s")
        step.set_downloader(downloader)
        step.run({"playlist": "My Mix", "playlist_index": 1})  # a YouTube Mix has no playlist_uploader
        self.assertEqual(downloader.params["outtmpl"]["default"], "%(playlist)s/one.%(ext)s")

    def test_tags_like_soundcloud(self):
        pp = self.links.YouTubeTagsPP(artist_from_title=True, album_mode="playlist")
        _files, info = pp.run({"title": "Aurora Vale - Neon Skyline", "uploader": "Aurora Vale - Topic",
                               "playlist": "Summer", "playlist_uploader": "dj - Topic", "playlist_index": 4})
        self.assertEqual(info["uploader"], "Aurora Vale")
        self.assertEqual((info["meta_artist"], info["meta_title"]), ("Aurora Vale", "Neon Skyline"))
        self.assertEqual((info["meta_album"], info["meta_album_artist"], info["meta_track"]), ("Summer", "dj", 4))
        _files, info = self.links.YouTubeTagsPP(False, "title").run({"title": "A - B", "artist": "Real"})
        self.assertNotIn("meta_artist", info)

    def test_unreadable_login_downloads_without_it_and_isnt_a_failure(self):
        output = self.links.Output()
        missing_profile = str(Path(tempfile.gettempdir()) / "no-such-firefox-profile")
        params = {"quiet": True, "cookiesfrombrowser": ("firefox", missing_profile, None, None), "logger": output}
        with mock.patch("builtins.print"), mock.patch.object(self.links.worker, "record_failure") as record:
            ydl = self.links.open_youtube(params, output)
        self.assertNotIn("cookiesfrombrowser", ydl.params)
        self.assertIs(ydl.params["logger"], output)  # yt-dlp's messages still reach the app
        self.assertEqual(output.errors, 0)
        record.assert_not_called()
        ydl.close()

    def test_errors_are_counted_and_logged(self):
        output = self.links.Output()
        with mock.patch.object(self.links.worker, "record_failure") as record, mock.patch("builtins.print"):
            output.debug("[youtube] Extracting URL: x")
            output.error("ERROR: [youtube] a: Video unavailable")
            output.error("Deprecated Feature: Support for Python version 3.10 has been deprecated")  # not a failure
        self.assertEqual(output.errors, 1)
        record.assert_called_once()

    def test_match_tags_use_the_soundcloud_track(self):
        from scdl_gui import youtube

        track = {"title": "Neon Skyline", "uploader": "Aurora Vale", "sc_url": "https://soundcloud.com/x",
                 "playlist": "Summer", "owner": "dj", "playlist_index": 7, "upload_date": "20250614"}
        with mock.patch.object(youtube, "ALBUM_MODE", "playlist"):
            info = youtube.tag_info("E:\\x\\Neon Skyline.m4a", track, "https://youtu.be/a")
        self.assertEqual((info["ext"], info["artist"], info["webpage_url"]), ("m4a", "Aurora Vale", "https://soundcloud.com/x"))
        self.assertEqual((info["meta_album"], info["meta_album_artist"], info["meta_track"]), ("Summer", "dj", "7"))


if __name__ == "__main__":
    unittest.main()
