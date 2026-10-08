"""Notification-area icon (the app keeps checking followed playlists with its window closed), and the
hand-off that brings the running app forward when it's started a second time."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from scdl_gui import APP_NAME

SHOW_REQUEST = "show-window.request"
SHOW_REQUEST_WAIT_SECONDS = 2.0
FRESH_REQUEST_SECONDS = 15.0  # a request this new found at start-up came from a launch during our start


def request_show(folder: Path) -> bool:
    """Ask the copy that's already running to show its window. True if it did (it removes the file);
    False if nothing picked the request up (e.g. it's an older version, or it's busy closing)."""
    request = folder / SHOW_REQUEST
    try:
        request.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        return False
    deadline = time.monotonic() + SHOW_REQUEST_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not request.exists():
            return True
        time.sleep(0.1)
    request.unlink(missing_ok=True)
    return False


class ShowRequestWatcher(QObject):
    """Emits `requested` when another start of the app asks this one to show its window."""

    requested = Signal()

    def __init__(self, folder: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request = folder / SHOW_REQUEST
        self._watcher = QFileSystemWatcher([str(folder)], self)
        self._watcher.directoryChanged.connect(self._check)
        try:
            age = time.time() - self._request.stat().st_mtime
        except OSError:
            return
        if age < FRESH_REQUEST_SECONDS:  # the app was opened while we were starting (e.g. with Windows)
            QTimer.singleShot(0, lambda: self._check(""))
        else:
            self._request.unlink(missing_ok=True)  # left over from a crash: not meant for us

    def _check(self, _path: str) -> None:
        if not self._request.exists():
            return
        try:
            self._request.unlink()
        except OSError:
            QTimer.singleShot(200, lambda: self._check(""))  # still being written: try again
            return
        self.requested.emit()


class Tray(QObject):
    open_requested = Signal()
    check_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon = QSystemTrayIcon(icon, self)
        self._icon.setToolTip(APP_NAME)
        self._menu = QMenu()
        self._menu.addAction(f"Open {APP_NAME}", self.open_requested.emit)
        self._menu.addAction("Check followed playlists now", self.check_requested.emit)
        self._menu.addSeparator()
        self._menu.addAction("Quit", self.quit_requested.emit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.messageClicked.connect(self.open_requested.emit)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_visible(self, visible: bool) -> None:
        self._icon.setVisible(visible)

    def is_visible(self) -> bool:
        return self._icon.isVisible()

    def set_tooltip(self, text: str) -> None:
        self._icon.setToolTip(f"{APP_NAME}\n{text}" if text else APP_NAME)

    def notify(self, title: str, text: str) -> None:
        if self._icon.isVisible():
            self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 8000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()
