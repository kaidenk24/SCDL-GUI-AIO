"""Qt behaviour that's easy to break: the YouTube matches list staying put, and layouts adapting to size."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from scdl_gui.matches import REVIEW, SEARCHING, MatchItem  # noqa: E402
from scdl_gui.settings import Settings  # noqa: E402
from scdl_gui.ui.state import AppState  # noqa: E402


def candidate(n: int) -> dict:
    return {"url": f"https://www.youtube.com/watch?v={n}", "title": f"Song {n}", "channel": "x", "duration": 100,
            "source": "YouTube", "score": 90 - n}


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class MatchesListTests(UiTest):
    def make_page(self, count: int):
        from scdl_gui.ui.matches_page import MatchesPage

        page = MatchesPage(AppState(Settings(library=self._tmp.name)))
        page._items = [MatchItem(track={"sc_id": str(n), "title": f"Track {n}", "target": f"t{n}"}, status=REVIEW,
                                 candidates=[candidate(1), candidate(2), candidate(3)]) for n in range(count)]
        page._refresh_list()
        page.resize(900, 400)
        page.show()
        self.app.processEvents()
        return page

    def test_list_keeps_its_place_when_another_track_changes(self):
        page = self.make_page(40)
        page.list.setCurrentRow(25)
        page.candidates.setCurrentItem(page.candidates.topLevelItem(2))
        scrollbar = page.list.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        position, entry = scrollbar.value(), page.list.item(3)

        other = page._items[3]
        other.status = SEARCHING
        page._changed()
        page._on_found({"key": other.key, "candidates": [candidate(7)], "query": "q"})

        self.assertEqual(page.list.currentRow(), 25)
        self.assertEqual(scrollbar.value(), position)
        self.assertIs(page.list.item(3), entry)  # updated in place, not rebuilt
        self.assertIn("Pick a match", entry.text())
        self.assertEqual(page._selected_candidate_url(), candidate(3)["url"])  # your pick in the detail stays

    def test_scheduled_checks_dont_bring_back_skipped_tracks(self):
        from scdl_gui.ui.matches_page import MatchesPage

        page = MatchesPage(AppState(Settings(library=self._tmp.name)))
        page.searcher.search = lambda items, settings: None
        track = {"sc_id": "1", "title": "Take Me", "target": "chill/take me"}
        page.add_track(track, scheduled=True)
        page.list.setCurrentRow(0)
        page._skip()
        page._remove_finished()
        page.add_track(dict(track), scheduled=True)  # the next automatic check reports it again
        self.assertEqual(page._items, [])
        reopened = MatchesPage(AppState(Settings(library=self._tmp.name)))  # remembered after a restart
        reopened.searcher.search = lambda items, settings: None
        reopened.add_track(dict(track), scheduled=True)
        self.assertEqual(reopened._items, [])
        reopened.add_track(dict(track))  # downloading the playlist yourself asks again
        self.assertEqual(len(reopened._items), 1)

    def test_added_and_removed_tracks(self):
        page = self.make_page(3)
        page.list.setCurrentRow(2)
        page._items.pop(0)
        page._items.append(MatchItem(track={"sc_id": "new", "title": "New", "target": "x"}, status=REVIEW))
        page._refresh_list()
        self.assertEqual([page.list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(page.list.count())],
                         [i.key for i in page._items])
        self.assertEqual(page._current().track["title"], "Track 2")


class LayoutTests(UiTest):
    def test_button_row_wraps_when_narrow(self):
        from scdl_gui.ui.widgets import FlowRow

        row = FlowRow(*(QPushButton(f"Button number {n}") for n in range(4)))
        one_line = row.sizeHint()
        self.assertEqual(row.layout().heightForWidth(one_line.width()), one_line.height())
        self.assertGreater(row.layout().heightForWidth(one_line.width() // 2), one_line.height())

    def test_splitter_stacks_on_narrow_pages(self):
        from scdl_gui.ui.widgets import ResponsiveSplitter

        splitter = ResponsiveSplitter(QWidget(), QWidget(), stack_below=700, wide_sizes=(300, 500), stacked_sizes=(100, 300))
        splitter.resize(900, 500)
        splitter.show()
        self.app.processEvents()
        self.assertEqual(splitter.orientation(), Qt.Orientation.Horizontal)
        splitter.resize(600, 500)
        self.app.processEvents()
        self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)

    def test_main_window_fits_small_screens_and_compacts_the_sidebar(self):
        from scdl_gui.ui import main_window

        window = self.make_window()
        screen = QApplication.primaryScreen().availableGeometry()
        self.assertLessEqual(window.width(), screen.width())
        self.assertLessEqual(window.height(), screen.height())
        window.resize(820, 540)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), main_window.SIDEBAR_COMPACT_WIDTH)
        self.assertEqual(window.nav.item(main_window.PAGE_PLAYLISTS).text(), "")
        window.resize(1300, 800)
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), main_window.SIDEBAR_WIDTH)
        self.assertIn("Playlists", window.nav.item(main_window.PAGE_PLAYLISTS).text())
        self.quit(window)

    def make_window(self):
        from scdl_gui.ui import main_window

        self._qsettings = mock.patch.object(main_window, "QSettings")  # keep the test out of the registry
        self._qsettings.start()
        self.addCleanup(self._qsettings.stop)
        self._qsettings_value = main_window.QSettings.return_value.value
        self._qsettings_value.return_value = None
        with mock.patch.object(main_window.MainWindow, "_check_login"), \
                mock.patch.object(main_window.MainWindow, "_after_start"):
            return main_window.MainWindow(AppState(Settings(library=self._tmp.name, offered_shortcuts=True)))

    def quit(self, window):
        from scdl_gui.ui import main_window

        window.watches.runner.is_running = lambda: False
        with mock.patch.object(main_window.QApplication, "quit") as quit_:
            window.quit_app()
        return quit_

    def test_closing_quits_even_if_saving_fails(self):
        from scdl_gui.ui import main_window

        window = self.make_window()
        window.show()
        with mock.patch.object(main_window, "save_settings", side_effect=PermissionError("locked")), \
                self.assertLogs("scdl_gui", level="WARNING"):
            quit_ = self.quit(window)
        quit_.assert_called_once()
        self.assertFalse(window.isVisible())

    def test_closing_hides_in_the_notification_area_when_following(self):
        from scdl_gui.ui import main_window

        window = self.make_window()
        window.lookup.lookup = lambda *_args: None  # no name look-up worker in tests
        window.watches.follow(["https://soundcloud.com/a/sets/b"], None)
        window.show()
        with mock.patch.object(main_window.Tray, "available", return_value=True), \
                mock.patch.object(main_window.QApplication, "quit") as quit_:
            window.close()
            self.assertFalse(window.isVisible())
            quit_.assert_not_called()
            self.assertTrue(window.tray.is_visible())
            window.bring_to_front()
            self.assertTrue(window.isVisible())
        self.quit(window)


class ShowRequestTests(UiTest):
    def test_second_start_hands_off_to_the_running_copy(self):
        from scdl_gui.ui import tray

        folder = Path(self._tmp.name)
        watcher = tray.ShowRequestWatcher(folder)
        shown = []
        watcher.requested.connect(lambda: shown.append(True))
        with mock.patch.object(tray.time, "sleep", side_effect=lambda _s: self.app.processEvents()):
            self.assertTrue(tray.request_show(folder))
        self.assertEqual(shown, [True])

    def test_nobody_listening(self):
        from scdl_gui.ui import tray

        with mock.patch.object(tray, "SHOW_REQUEST_WAIT_SECONDS", 0.3):
            self.assertFalse(tray.request_show(Path(self._tmp.name)))
        self.assertFalse((Path(self._tmp.name) / tray.SHOW_REQUEST).exists())

    def test_request_made_while_starting_is_honoured_and_an_old_one_ignored(self):
        from scdl_gui.ui import tray

        folder = Path(self._tmp.name)
        request = folder / tray.SHOW_REQUEST
        request.write_text("x")
        shown = []
        watcher = tray.ShowRequestWatcher(folder)
        watcher.requested.connect(lambda: shown.append(True))
        self.app.processEvents()
        self.assertEqual(shown, [True])
        request.write_text("x")
        os.utime(request, (1, 1))  # from a crash long ago
        old = tray.ShowRequestWatcher(folder)
        old.requested.connect(lambda: shown.append(True))
        self.app.processEvents()
        self.assertEqual(shown, [True])
        self.assertFalse(request.exists())


class PlaylistsTableTests(UiTest):
    def test_refresh_leaves_the_save_to_cell_being_edited_alone(self):
        from scdl_gui.ui.playlists_page import COL_FOLDER, WatchModel
        from scdl_gui.ui.watch_controller import WatchController

        controller = WatchController(AppState(Settings(library=self._tmp.name)), lambda: True)
        controller.follow(["https://soundcloud.com/a/sets/b", "https://soundcloud.com/a/sets/c"], None)
        model = WatchModel(controller)
        touched = []
        model.dataChanged.connect(lambda first, last: touched.append((first.row(), first.column(), last.column())))
        controller.update_watch("https://soundcloud.com/a/sets/c", last_result="2 new tracks")
        self.assertTrue(touched)
        self.assertTrue(all(row == 1 and not first <= COL_FOLDER <= last for row, first, last in touched))
        touched.clear()
        controller.update_watch("https://soundcloud.com/a/sets/c", folder="Gym")
        self.assertIn((1, 0, COL_FOLDER + 2), touched)
        controller._timer.stop()


if __name__ == "__main__":
    unittest.main()
