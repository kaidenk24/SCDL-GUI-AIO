"""Tests for followed playlists: the schedule, results, persistence and the Qt controller."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scdl_gui import settings as settings_mod  # noqa: E402
from scdl_gui import watches
from scdl_gui.parsing import JobCounts  # noqa: E402
from scdl_gui.watches import Watch  # noqa: E402

HOUR = 3600.0
A, B, C = (f"https://soundcloud.com/dj/sets/{name}" for name in ("a", "b", "c"))


class TempAppData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class ScheduleTests(unittest.TestCase):
    def test_due_after_the_interval_and_only_when_enabled(self):
        now = 100 * HOUR
        fresh = Watch(A, last_checked=now - 2 * HOUR)
        stale = Watch(B, last_checked=now - 3 * HOUR)
        paused = Watch(C, enabled=False)
        self.assertEqual(watches.due_watches([fresh, stale, paused], now, 3), [stale])
        self.assertTrue(watches.is_due(Watch(A), now, 24))  # never checked

    def test_next_check(self):
        items = [Watch(A, last_checked=10 * HOUR), Watch(B, last_checked=5 * HOUR), Watch(C, enabled=False)]
        self.assertEqual(watches.next_check_at(items, 3, 9 * HOUR), 8 * HOUR)
        self.assertIsNone(watches.next_check_at([Watch(A, enabled=False)], 3, 9 * HOUR))

    def test_failed_check_is_retried_soon_not_a_whole_interval_later(self):
        checked = Watch(A, last_checked=10 * HOUR, last_result="Up to date")
        failed = watches.record_check(checked, 20 * HOUR, "Failed - see Activity", JobCounts())
        self.assertEqual(failed.last_checked, 10 * HOUR)  # "last checked" still shows the last good check
        self.assertEqual(failed.last_result, "Failed - see Activity")
        self.assertFalse(watches.is_due(failed, 20 * HOUR + 60, 24))
        self.assertTrue(watches.is_due(failed, 20 * HOUR + watches.RETRY_AFTER_FAILURE, 24))
        ok = watches.record_check(failed, 21 * HOUR, "Done", JobCounts())
        self.assertEqual((ok.retry_at, ok.last_checked), (0.0, 21 * HOUR))
        self.assertFalse(watches.is_due(ok, 22 * HOUR, 24))

    def test_clock_turned_back_does_not_stall_checks(self):
        self.assertTrue(watches.is_due(Watch(A, last_checked=50 * HOUR), 10 * HOUR, 3))

    def test_adding_skips_links_already_followed(self):
        items, added = watches.add_watches([Watch(A, folder="Gym")], [A, B, B], "Car")
        self.assertEqual(added, [B])
        self.assertEqual([(w.url, w.folder) for w in items], [(A, "Gym"), (B, "Car")])


class ResultTests(unittest.TestCase):
    def test_result_text(self):
        self.assertEqual(watches.result_text("Done - 0 new", JobCounts(skipped=40)), "Up to date")
        self.assertEqual(watches.result_text("Done", JobCounts(saved=1)), "1 new track")
        self.assertEqual(watches.result_text("Done", JobCounts(saved=2, to_match=1, failed=1)),
                         "2 new tracks, 1 to match on YouTube, 1 failed")
        self.assertEqual(watches.result_text("Failed - see Activity", JobCounts()), "Failed - see Activity")

    def test_record_check(self):
        watch = Watch(A, total_new=5, last_new=1.0)
        quiet = watches.record_check(watch, 50.0, "Done", JobCounts(skipped=9))
        self.assertEqual((quiet.last_checked, quiet.last_result, quiet.total_new, quiet.last_new), (50.0, "Up to date", 5, 1.0))
        busy = watches.record_check(watch, 60.0, "Done", JobCounts(saved=3))
        self.assertEqual((busy.total_new, busy.last_new), (8, 60.0))

    def test_describe_times(self):
        self.assertEqual(watches.describe_age(0, 1000), "Never")
        self.assertEqual(watches.describe_age(1000, 1030), "Just now")
        self.assertEqual(watches.describe_age(0.5, 0.5 + 5 * 60), "5 min ago")
        self.assertEqual(watches.describe_age(1, 1 + 3 * HOUR), "3 h ago")
        self.assertEqual(watches.describe_age(1, 1 + 26 * HOUR), "1 day ago")
        self.assertEqual(watches.describe_wait(30), "now")
        self.assertEqual(watches.describe_wait(14 * 60), "in 14 min")
        self.assertEqual(watches.describe_wait(2 * HOUR + 14 * 60), "in 2 h 14 min")
        self.assertEqual(watches.describe_wait(3 * HOUR), "in 3 h")


class StorageTests(TempAppData):
    def test_round_trip(self):
        items = [Watch(A, folder=None, name="A", last_checked=5.0, total_new=2), Watch(B, folder="E:\\Car", enabled=False)]
        watches.save_watches(items)
        self.assertEqual(watches.load_watches(), items)

    def test_bad_entries_are_ignored_or_repaired(self):
        raw = [{"url": A, "total_new": "lots", "enabled": "yes", "last_checked": None, "folder": 7, "bogus": 1},
               {"url": A}, {"name": "no url"}, "junk"]
        (settings_mod.data_dir() / watches.FILE_NAME).write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(watches.load_watches(), [Watch(A)])

    def test_unreadable_file_is_kept_aside_not_overwritten(self):
        path = settings_mod.data_dir() / watches.FILE_NAME
        path.write_text("{not json", encoding="utf-8")
        with self.assertLogs("scdl_gui", level="WARNING"):
            self.assertEqual(watches.load_watches(), [])
        self.assertEqual(path.with_suffix(".json.bad").read_text(encoding="utf-8"), "{not json")

    def test_interval_setting_is_validated(self):
        (settings_mod.data_dir() / "settings.json").write_text(json.dumps({"watch_interval_hours": 5}), encoding="utf-8")
        self.assertEqual(settings_mod.load_settings().watch_interval_hours, 3)


class ControllerTests(TempAppData):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from scdl_gui.settings import Settings
        from scdl_gui.ui import watch_controller
        from scdl_gui.ui.state import AppState

        self.library = Path(self._tmp.name) / "Music"
        self.library.mkdir()
        self.state = AppState(Settings(library=str(self.library), watch_interval_hours=3))
        self.blocked = False
        self._ffmpeg = mock.patch.object(watch_controller, "find_ffmpeg", return_value="ffmpeg.exe")
        self._ffmpeg.start()
        self.controller = watch_controller.WatchController(self.state, lambda: self.blocked)
        self.started: list = []
        self.controller.runner.start = lambda entries, _settings: self.started.append(entries)
        self.controller.runner.is_running = lambda: bool(self.started) and not self.finished
        self.finished = False

    def tearDown(self):
        self.app.processEvents()  # run queued ticks while find_ffmpeg is still patched
        self.controller._timer.stop()
        self._ffmpeg.stop()
        super().tearDown()

    def follow(self, *urls, **fields):
        self.controller.follow(list(urls), None)
        for url in urls:
            if fields:
                self.controller.update_watch(url, **fields)

    def run_finished(self, row, status, counts):
        self.controller.runner.job_finished.emit(row, status, counts)

    def test_checks_due_playlists_and_records_the_result(self):
        self.follow(A, B)
        self.controller.update_watch(B, last_checked=time.time())  # checked a moment ago: not due
        new_tracks = []
        self.controller.new_tracks.connect(lambda name, count: new_tracks.append((name, count)))
        self.controller.tick()
        self.assertEqual([job.url for _row, job in self.started[0]], [A])
        self.run_finished(0, "Done - 2 new", JobCounts(saved=2, skipped=10))
        watch = next(w for w in self.controller.watches if w.url == A)
        self.assertEqual((watch.last_result, watch.total_new), ("2 new tracks", 2))
        self.assertGreater(watch.last_checked, 0)
        self.assertEqual(new_tracks, [(A, 2)])
        self.assertEqual(watches.load_watches(), self.controller.watches)  # saved

    def test_never_runs_alongside_your_own_downloads(self):
        self.follow(A)
        self.blocked = True
        self.controller.tick()
        self.assertEqual(self.started, [])

    def test_a_stopped_check_runs_again(self):
        self.follow(A)
        self.controller.tick()
        self.run_finished(0, "Stopped", JobCounts(saved=1))
        self.assertEqual(self.controller.watches[0].last_checked, 0.0)

    def test_missing_library_drive_waits(self):
        self.follow(A)
        self.state.update(library=str(self.library / "unplugged"))
        self.controller.tick()
        self.assertEqual(self.started, [])
        self.assertIn("library folder", self.controller.problem())

    def test_check_now_includes_paused_and_recent_playlists(self):
        self.follow(A, enabled=False, last_checked=time.time())
        self.controller.check_now([A])
        self.assertEqual([job.url for _row, job in self.started[0]], [A])

    def test_folder_changed_during_a_check_is_kept(self):
        self.follow(A)
        self.controller.tick()
        self.controller.update_watch(A, folder="Gym")
        self.run_finished(0, "Done", JobCounts())
        self.assertEqual(self.controller.watches[0].folder, "Gym")

    def test_unfollowed_during_a_check_stops_it(self):
        self.follow(A)
        self.controller.tick()
        with mock.patch.object(self.controller.runner, "stop") as stop:
            self.controller.unfollow([A])
        stop.assert_called_once()
        self.run_finished(0, "Stopped", JobCounts(saved=1))
        self.assertEqual(self.controller.watches, [])

    def test_pausing_a_finished_link_mid_run_does_not_stop_the_others(self):
        self.follow(A, B)
        self.controller.tick()
        self.run_finished(0, "Done", JobCounts())
        with mock.patch.object(self.controller.runner, "stop") as stop:
            self.controller.update_watch(A, enabled=False)
            stop.assert_not_called()
            self.controller.update_watch(B, enabled=False)
            stop.assert_called_once()

    def test_failed_check_waits_for_the_retry(self):
        self.follow(A)
        self.controller.tick()
        self.run_finished(0, "Failed - see Activity", JobCounts())
        self.finished = True
        self.controller.runner.finished.emit(JobCounts(), False)
        self.assertEqual(len(self.started), 1)  # not retried straight away
        self.assertGreater(self.controller.watches[0].retry_at, time.time())

    def test_end_of_run_runs_what_was_asked_for_meanwhile(self):
        self.follow(A, B)
        self.controller.update_watch(B, last_checked=time.time())
        self.controller.tick()
        self.controller.check_now([B])  # asked during the run: waits its turn
        self.assertEqual(self.controller.live_status(B), "Waiting...")
        self.run_finished(0, "Done", JobCounts())
        self.finished = True
        self.controller.runner.finished.emit(JobCounts(), False)
        self.app.processEvents()
        self.assertEqual([job.url for _row, job in self.started[-1]], [B])


if __name__ == "__main__":
    unittest.main()
