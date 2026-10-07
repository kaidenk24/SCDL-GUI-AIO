"""Main window: sidebar navigation, pages, and the bottom bar with Start/Stop and progress."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from scdl_gui import APP_NAME, APP_VERSION
from scdl_gui.engine import find_ffmpeg
from scdl_gui.parsing import JobCounts
from scdl_gui.runner import DownloadRunner, LoginChecker, LookupRunner
from scdl_gui.settings import load_queue, resource_path, save_queue, save_settings
from scdl_gui.ui import theme
from scdl_gui.ui.account_page import AccountPage
from scdl_gui.ui.activity_page import ActivityPage
from scdl_gui.ui.audio_page import AudioPage
from scdl_gui.ui.layout_page import LayoutPage
from scdl_gui.ui.matches_page import MatchesPage
from scdl_gui.ui.queue_model import QueueModel
from scdl_gui.ui.queue_page import QueuePage
from scdl_gui.system import create_shortcuts, shortcut_folders
from scdl_gui.ui.setup_page import SetupPage
from scdl_gui.ui.state import AppState
from scdl_gui.ui.updater import UpdateBanner, UpdateController
from scdl_gui.ui.widgets import StatusPill, hbox, label
from scdl_gui.updates import take_update_error

NAV = (  # (title, Segoe Fluent/MDL2 icon code point)
    ("Queue", "\ue896"),
    ("YouTube matches", "\ue71e"),
    ("Save layout", "\ue8b7"),
    ("Audio", "\ue767"),
    ("Account & tags", "\ue77b"),
    ("Activity", "\ue81c"),
    ("Setup & updates", "\ue713"),
)
PAGE_QUEUE, PAGE_MATCHES, PAGE_LAYOUT, PAGE_AUDIO, PAGE_ACCOUNT, PAGE_ACTIVITY, PAGE_SETUP = range(len(NAV))


def glyph_icon(glyph: str, color: str, size: int = 18) -> QIcon:
    families = QFontDatabase.families()
    family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), None)
    if family is None:
        return QIcon()
    pixmap = QPixmap(QSize(size, size) * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont(family)
    font.setPixelSize(size - 2)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(resource_path("assets", "icon.ico"))))
        self.resize(1240, 800)
        self.setMinimumSize(980, 640)
        self._state = state
        self._model = QueueModel(load_queue())
        self._run_rows: list[int] = []
        self._finished_rows = 0

        self.runner = DownloadRunner(self)
        self.lookup = LookupRunner(self)
        self.login = LoginChecker(self)

        self.queue_page = QueuePage(state, self._model)
        self.matches_page = MatchesPage(state)
        self.layout_page = LayoutPage(state)
        self.audio_page = AudioPage(state)
        self.account_page = AccountPage(state)
        self.activity_page = ActivityPage(state)
        self.setup_page = SetupPage(state)
        self.updater = UpdateController(state, self, self._confirm_quit_for_update)
        self.update_banner = UpdateBanner()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        main = QHBoxLayout()
        main.setSpacing(0)
        main.addWidget(self._build_sidebar())
        content = QVBoxLayout()
        content.setSpacing(0)
        content.addWidget(self.update_banner)
        self.pages = QStackedWidget()
        pages = (self.queue_page, self.matches_page, self.layout_page, self.audio_page,
                 self.account_page, self.activity_page, self.setup_page)
        for page in pages:
            self.pages.addWidget(page)
        content.addWidget(self.pages, 1)
        main.addLayout(content, 1)
        root.addLayout(main, 1)
        root.addWidget(self._build_bottom_bar())
        self.setCentralWidget(central)
        self.nav.setCurrentRow(PAGE_QUEUE)
        self._set_match_badge(self.matches_page.needs_user())

        self._wire()
        self._restore_geometry()
        self._refresh_library()
        self._set_running(False)
        QTimer.singleShot(300, self._check_login)
        QTimer.singleShot(1500, self._after_start)

    # ---- layout
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 22, 0, 16)
        layout.setSpacing(4)
        title = label(APP_NAME, "AppTitle", wrap=True)
        title.setContentsMargins(22, 0, 16, 14)
        layout.addWidget(title)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for name, glyph in NAV:
            self.nav.addItem(QListWidgetItem(glyph_icon(glyph, theme.SIDEBAR_TEXT), f"  {name}"))
        self.nav.currentRowChanged.connect(lambda row: self.pages.setCurrentIndex(row))
        layout.addWidget(self.nav, 1)
        self.login_pill = StatusPill()
        self.login_pill.setContentsMargins(0, 0, 0, 0)
        pill_row = hbox(self.login_pill, None, margins=(22, 0, 16, 6))
        layout.addLayout(pill_row)
        version = label(f"Version {APP_VERSION}", "AppVersion")
        version.setContentsMargins(22, 0, 0, 0)
        layout.addWidget(version)
        return sidebar

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("BottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(18)

        library = QVBoxLayout()
        library.setSpacing(2)
        library.addWidget(label("Library folder", "Hint"))
        self.library_label = label("", "CardTitle")
        self.library_label.setMaximumWidth(360)
        change = QPushButton("Change...")
        change.clicked.connect(self._choose_library)
        open_ = QPushButton("Open")
        open_.clicked.connect(self._open_library)
        library.addLayout(hbox(self.library_label, change, open_))
        layout.addLayout(library)

        progress = QVBoxLayout()
        progress.setSpacing(4)
        self.status_main = label("Ready.")
        self.status_counts = label("", "Hint")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        progress.addWidget(self.status_main)
        progress.addWidget(self.progress)
        progress.addWidget(self.status_counts)
        layout.addLayout(progress, 1)

        self.start_button = QPushButton("  Start downloads")
        self.start_button.setObjectName("Primary")
        self.start_button.setIcon(glyph_icon("\ue768", "#FFFFFF"))
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("Stop")
        self.stop_button.clicked.connect(self.runner.stop)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.start_button)
        return bar

    # ---- wiring
    def _wire(self) -> None:
        state = self._state
        self._save_settings_timer = QTimer(self, singleShot=True, interval=400, timeout=lambda: save_settings(state.settings))
        self._save_queue_timer = QTimer(self, singleShot=True, interval=600, timeout=lambda: save_queue(self._model.jobs))
        state.settings_changed.connect(self._on_settings_changed)
        self._model.changed.connect(self._save_queue_timer.start)

        self.queue_page.links_added.connect(self._lookup_new)
        self.queue_page.lookup_requested.connect(lambda urls: urls and self.lookup.lookup(urls, state.settings))
        self.lookup.described.connect(self._on_described)
        self.account_page.check_login_requested.connect(self._check_login)
        self.login.checked.connect(self._on_login)
        self.login.youtube_checked.connect(self.account_page.set_youtube_state)
        self.matches_page.needs_user_changed.connect(self._set_match_badge)
        self.setup_page.check_updates_requested.connect(lambda: self.updater.check(manual=True))
        self.updater.message.connect(self.setup_page.show_update_result)
        self.updater.available.connect(self.update_banner.show_release)
        self.update_banner.update_clicked.connect(self.updater.install)
        self.update_banner.skip_clicked.connect(lambda: (self.updater.skip(), self.update_banner.hide()))

        r = self.runner
        r.log.connect(self.activity_page.add)
        r.job_started.connect(self._on_job_started)
        r.job_progress.connect(self._on_job_progress)
        r.job_named.connect(lambda row, name: self._model.job(row).name or self._model.update(row, name=name))
        r.job_finished.connect(self._on_job_finished)
        r.totals_changed.connect(lambda c: self.status_counts.setText(self._counts_text(c)))
        r.status.connect(self.status_main.setText)
        r.finished.connect(self._on_run_finished)
        r.drm_found.connect(self.matches_page.add_track)

    def _on_settings_changed(self, settings) -> None:
        self._save_settings_timer.start()
        self._refresh_library()
        if (settings.use_login, settings.youtube_login, settings.firefox_profile) != getattr(self, "_login_key", None):
            self._check_login()

    # ---- library
    def _refresh_library(self) -> None:
        path = self._state.settings.library
        metrics = self.library_label.fontMetrics()
        self.library_label.setText(metrics.elidedText(path, Qt.TextElideMode.ElideMiddle, 340))
        self.library_label.setToolTip(path)

    def _choose_library(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Library folder", self._state.settings.library)
        if path:
            self._state.update(library=os.path.normpath(path))

    def _open_library(self) -> None:
        path = Path(self._state.settings.library)
        if path.is_dir():
            os.startfile(path)  # noqa: S606

    # ---- login & lookups
    def _check_login(self) -> None:
        settings = self._state.settings
        self._login_key = (settings.use_login, settings.youtube_login, settings.firefox_profile)
        self._on_login("checking", "")
        self.account_page.set_youtube_state("checking")
        self.login.check(settings)

    def _set_match_badge(self, waiting: int) -> None:
        title = NAV[PAGE_MATCHES][0]
        self.nav.item(PAGE_MATCHES).setText(f"  {title}  ({waiting})" if waiting else f"  {title}")

    def _on_login(self, state: str, detail: str) -> None:
        self.account_page.set_login_state(state, detail)
        level, text = {
            "yes": ("ok", "Logged in"), "no": ("warn", "Not logged in"), "off": ("busy", "No login"),
            "checking": ("busy", "Checking login..."),
        }.get(state, ("error", "Login problem"))
        self.login_pill.set_state(level, text)
        self.login_pill.setToolTip("SoundCloud login via Firefox - see Account & tags")

    def _lookup_new(self, urls: list[str]) -> None:
        if self._state.settings.lookup_names and urls:
            self.lookup.lookup(urls, self._state.settings)

    def _on_described(self, data: dict) -> None:
        for row in self._model.rows_for_url(data.get("url", "")):
            if data.get("error"):
                if self._model.job(row).status == "Queued":
                    self._model.update(row, status=f"Check link: {data['error'][:80]}")
                continue
            title = data.get("title") or ""
            kind = data.get("kind") or self._model.job(row).kind
            if kind == "Track" and data.get("uploader"):
                title = f"{title}  ({data['uploader']})"
            self._model.update(row, name=title, kind=kind)
        self._save_queue_timer.start()

    # ---- running
    def _start(self) -> None:
        settings = self._state.settings
        rows = [row for row, job in enumerate(self._model.jobs) if job.enabled]
        if not rows:
            QMessageBox.information(self, APP_NAME, "Add some links and tick them in the queue first.")
            self.nav.setCurrentRow(PAGE_QUEUE)
            return
        if not find_ffmpeg(settings):
            QMessageBox.warning(self, APP_NAME, "FFmpeg wasn't found, so nothing can be converted to MP3.\n"
                                "Install it with one click on the Setup & updates page.")
            self.nav.setCurrentRow(PAGE_SETUP)
            return
        library = Path(settings.library)
        if not library.is_dir():
            answer = QMessageBox.question(self, APP_NAME, f"The library folder doesn't exist:\n{library}\n\nCreate it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                library.mkdir(parents=True, exist_ok=True)
            except OSError as err:
                QMessageBox.warning(self, APP_NAME, f"Couldn't create it: {err}")
                return
        save_settings(settings)
        for row in rows:
            self._model.update(row, status="Waiting")
        self._run_rows = rows
        self._finished_rows = 0
        self.activity_page.add("info", f"Starting {len(rows)} link(s) - library: {library}")
        self._set_running(True)
        self.runner.start([(row, self._model.job(row)) for row in rows], settings)

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setVisible(running)
        if not running:
            self.progress.setValue(0)

    def _on_job_started(self, row: int) -> None:
        self._model.update(row, status="Starting...")
        job = self._model.job(row)
        self.status_main.setText(f"Link {self._finished_rows + 1} of {len(self._run_rows)}: {job.name or job.url}")
        self._set_progress(0, 0)

    def _on_job_progress(self, row: int, item: int, total: int, track: str) -> None:
        job = self._model.job(row)
        if total:
            self._model.update(row, status=f"Downloading {item} of {total}")
        place = f"Link {self._finished_rows + 1} of {len(self._run_rows)}: {job.name or job.url}"
        detail = f" - track {item} of {total}" if total else ""
        self.status_main.setText(place + detail + (f": {track}" if track else ""))
        self._set_progress(item, total)

    def _set_progress(self, item: int, total: int) -> None:
        jobs = max(len(self._run_rows), 1)
        within = (item - 1) / total if total and item else 0
        self.progress.setValue(int(1000 * (self._finished_rows + within) / jobs))

    def _on_job_finished(self, row: int, status: str) -> None:
        clean = status.startswith("Done") and "failed" not in status
        self._model.update(row, status=status, enabled=not clean)  # untick links that finished cleanly
        self._finished_rows += 1
        self._set_progress(0, 0)
        self._save_queue_timer.start()

    def _on_run_finished(self, totals: JobCounts, stopped: bool) -> None:
        self._set_running(False)
        self._model.changed.emit()
        notes = ["Stopped." if stopped else "Finished."]
        if totals.to_match:
            notes.append(f"{totals.to_match} track(s) need your OK on the YouTube matches page.")
        if totals.failed:
            notes.append("See Activity for what failed.")
        self.status_main.setText(" ".join(notes))
        self.status_counts.setText(self._counts_text(totals))
        self.progress.setValue(0 if stopped else 1000)
        QApplication.alert(self)

    @staticmethod
    def _counts_text(counts: JobCounts) -> str:
        text = f"{counts.saved} new  -  {counts.skipped} already had  -  {counts.failed} failed"
        return text + (f"  -  {counts.to_match} to match on YouTube" if counts.to_match else "")

    # ---- startup & updates
    def _after_start(self) -> None:
        failed_update = take_update_error()
        if failed_update:
            QMessageBox.warning(self, APP_NAME, f"The last update didn't finish:\n{failed_update}\n\n"
                                "Download the latest version from the project page.")
        if not self._state.settings.offered_shortcuts:
            self._state.update(offered_shortcuts=True)
            answer = QMessageBox.question(self, APP_NAME, "Add SoundCloud Downloader to your Start menu and desktop?")
            if answer == QMessageBox.StandardButton.Yes:
                create_shortcuts(list(shortcut_folders()))
        if not find_ffmpeg(self._state.settings):
            answer = QMessageBox.question(
                self, APP_NAME, "FFmpeg is needed to make MP3s and isn't installed yet. Set it up now?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.nav.setCurrentRow(PAGE_SETUP)
        self.updater.check_on_start()

    def _confirm_quit_for_update(self) -> bool:
        if not self.runner.is_running():
            return True
        answer = QMessageBox.question(self, APP_NAME, "Downloads are running. Stop them and update now?")
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.runner.stop()
        return True

    # ---- window state
    def _restore_geometry(self) -> None:
        geometry = QSettings(APP_NAME, "window").value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:
        if self.runner.is_running():
            answer = QMessageBox.question(self, APP_NAME, "Downloads are still running. Stop them and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.stop()
        QSettings(APP_NAME, "window").setValue("geometry", self.saveGeometry())
        save_settings(self._state.settings)
        save_queue(self._model.jobs)
        event.accept()
