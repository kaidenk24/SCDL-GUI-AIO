"""Update banner + the controller that checks GitHub and installs updates in the background."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMessageBox, QProgressDialog, QPushButton, QWidget

from scdl_gui import APP_NAME, APP_VERSION
from scdl_gui.ui import theme
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import label
from scdl_gui.updates import (
    CHECK_INTERVAL_SECONDS,
    Release,
    UpdateError,
    download_asset,
    fetch_latest,
    git_update,
    install_kind,
    is_newer,
    prepare_exe_update,
    restart_command,
    run_update_script,
)


class UpdateBanner(QFrame):
    update_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {theme.ACCENT_SOFT}; border-bottom: 1px solid {theme.ACCENT_LINE}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 12, 8)
        self.text = label("")
        self.text.setStyleSheet("background: transparent; border: none; font-weight: 600;")
        notes = QPushButton("What's new")
        notes.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._release.page_url)) if self._release else None)
        update = QPushButton("Update now")
        update.setObjectName("Primary")
        update.clicked.connect(self.update_clicked.emit)
        skip = QPushButton("Skip this version")
        skip.clicked.connect(self.skip_clicked.emit)
        later = QPushButton("Later")
        later.clicked.connect(self.hide)
        layout.addWidget(self.text, 1)
        for button in (notes, skip, later, update):
            layout.addWidget(button)
        self._release: Release | None = None
        self.hide()

    def show_release(self, release: Release) -> None:
        self._release = release
        self.text.setText(f"{APP_NAME} {release.version} is available - you have {APP_VERSION}.")
        self.show()


class _Bridge(QObject):
    """Signals emitted from worker threads arrive on the UI thread."""

    checked = Signal(object, str, bool)  # Release | None, error, manual
    progress = Signal(int, int)
    prepared = Signal(object, str)  # script path | None, error
    git_done = Signal(str, str)  # log, error


class UpdateController(QObject):
    """can_quit() lets the window refuse (e.g. downloads running) before an update restarts the app."""

    available = Signal(object)  # Release
    message = Signal(str)  # result of a manual check

    def __init__(self, state: AppState, parent: QWidget, can_quit: Callable[[], bool]) -> None:
        super().__init__(parent)
        self._state = state
        self._parent = parent
        self._can_quit = can_quit
        self._bridge = _Bridge()
        self._bridge.checked.connect(self._on_checked)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.prepared.connect(self._on_prepared)
        self._bridge.git_done.connect(self._on_git_done)
        self._progress: QProgressDialog | None = None
        self._release: Release | None = None
        self._checking = False

    # ---- checking
    def check_on_start(self) -> None:
        settings = self._state.settings
        if settings.check_updates and time.time() - settings.last_update_check >= CHECK_INTERVAL_SECONDS:
            self.check(manual=False)

    def check(self, manual: bool = True) -> None:
        if self._checking:
            return
        self._checking = True

        def work() -> None:
            try:
                self._bridge.checked.emit(fetch_latest(), "", manual)
            except UpdateError as err:
                self._bridge.checked.emit(None, str(err), manual)

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, release: Release | None, error: str, manual: bool) -> None:
        self._checking = False
        if error:
            if manual:
                self.message.emit(f"Couldn't check for updates: {error}")
            return
        self._state.update(last_update_check=time.time())
        if release and is_newer(release.version):
            if manual or release.version != self._state.settings.skipped_version:
                self._release = release
                self.available.emit(release)
            if manual:
                self.message.emit(f"Version {release.version} is available.")
        elif manual:
            self.message.emit(f"You're on the latest version ({APP_VERSION}).")

    def skip(self) -> None:
        if self._release:
            self._state.update(skipped_version=self._release.version)

    # ---- installing
    def install(self) -> None:
        release = self._release
        if release is None:
            return
        kind = install_kind()
        if kind == "source":
            QMessageBox.information(
                self._parent, "Update",
                "This copy was downloaded as source code, so it can't update itself.\n"
                "The release page will open - download the new version from there.",
            )
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        if not self._can_quit():
            return
        if kind == "git":
            self._show_progress("Updating from GitHub...", busy=True)
            threading.Thread(target=self._git_work, daemon=True).start()
        else:
            self._show_progress(f"Downloading version {release.version}...", busy=False)
            threading.Thread(target=self._exe_work, args=(release,), daemon=True).start()

    def _exe_work(self, release: Release) -> None:
        try:
            zip_path = download_asset(release, lambda done, total: self._bridge.progress.emit(done, total))
            self._bridge.prepared.emit(prepare_exe_update(zip_path), "")
        except UpdateError as err:
            self._bridge.prepared.emit(None, str(err))

    def _git_work(self) -> None:
        try:
            self._bridge.git_done.emit(git_update(), "")
        except UpdateError as err:
            self._bridge.git_done.emit("", str(err))

    def _show_progress(self, text: str, busy: bool) -> None:
        self._progress = QProgressDialog(text, None, 0, 0 if busy else 1000, self._parent)
        self._progress.setWindowTitle("Updating")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.show()

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress and total:
            self._progress.setValue(int(1000 * done / total))

    def _close_progress(self) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None

    def _on_prepared(self, script, error: str) -> None:
        self._close_progress()
        if error:
            QMessageBox.warning(self._parent, "Update", f"The update couldn't be installed:\n{error}")
            return
        QMessageBox.information(self._parent, "Update", "The update is ready. The app will now close, update and reopen.")
        run_update_script(script)
        self._quit()

    def _on_git_done(self, _log: str, error: str) -> None:
        self._close_progress()
        if error:
            QMessageBox.warning(self._parent, "Update", f"The update failed:\n{error}")
            return
        answer = QMessageBox.question(self._parent, "Update", "Updated. Restart now to use the new version?")
        if answer == QMessageBox.StandardButton.Yes:
            subprocess.Popen(restart_command(), close_fds=True)
            self._quit()

    def _quit(self) -> None:
        """Close through the window (saves the queue and settings), then leave the event loop."""
        self._parent.close()
        QApplication.quit()
