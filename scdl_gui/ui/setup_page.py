"""Setup & updates page: helper programs, update checks, shortcuts, maintenance and about."""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QMessageBox, QPushButton

from scdl_gui import APP_VERSION, GITHUB_URL
from scdl_gui.engine import failed_log_path, find_ffmpeg, find_js_runtime
from scdl_gui.settings import Settings, data_dir
from scdl_gui.system import FFMPEG, NODE, create_shortcuts, shortcut_folders
from scdl_gui.ui.potoken_card import PotCard
from scdl_gui.ui.state import AppState
from scdl_gui.ui.tool_installer import ToolInstaller
from scdl_gui.ui.widgets import Card, Page, hbox, label
from scdl_gui.updates import install_kind

INSTALL_KINDS = {"exe": "app", "git": "git checkout", "source": "source download"}
DISCLAIMER = (
    "An unofficial tool - not affiliated with or endorsed by SoundCloud or YouTube. Only download music you "
    "have the right to keep, and respect artists and each site's terms. Licensed under GPL-2.0-or-later."
)


def open_path(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SetupPage(Page):
    check_updates_requested = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__("Setup & updates", "Helper programs, updates, shortcuts and information about the app.")
        self._state = state
        self.installer = ToolInstaller(self)
        self.installer.finished.connect(lambda _name, _ok: self._load())
        self.body.addWidget(self._build_helpers())
        self.pot_card = PotCard(state)
        self.installer.finished.connect(lambda _name, _ok: self.pot_card.refresh())
        self.body.addWidget(self.pot_card)
        self.body.addWidget(self._build_updates())
        self.body.addWidget(self._build_files())
        self.body.addWidget(self._build_about())
        self.finish()
        state.settings_changed.connect(lambda _s: self._load())
        self._load()

    # ---- cards
    def _build_helpers(self) -> Card:
        card = Card("Helper programs", "Two free programs do the heavy lifting. Both can be installed with one click.")
        self.ffmpeg_status = label("", wrap=True)
        self.install_ffmpeg = QPushButton("Install FFmpeg for me")
        self.install_ffmpeg.clicked.connect(lambda: self.installer.install(FFMPEG))
        choose = QPushButton("Choose ffmpeg.exe...")
        choose.clicked.connect(self._choose_ffmpeg)
        auto = QPushButton("Find automatically")
        auto.clicked.connect(lambda: self._state.update(ffmpeg_path=""))
        card.body.addWidget(label("FFmpeg - converts audio to MP3 (required)", "CardTitle"))
        card.body.addWidget(self.ffmpeg_status)
        card.body.addLayout(hbox(self.install_ffmpeg, choose, auto, None))

        self.node_status = label("", wrap=True)
        self.install_node = QPushButton("Install Node.js for me")
        self.install_node.clicked.connect(lambda: self.installer.install(NODE))
        card.body.addSpacing(6)
        card.body.addWidget(label("Node.js - needed for YouTube matches and PO tokens", "CardTitle"))
        card.body.addWidget(self.node_status)
        card.body.addLayout(hbox(self.install_node, None))
        return card

    def _build_updates(self) -> Card:
        card = Card("Updates")
        self.version = label("")
        self.auto_check = QCheckBox("Check for updates automatically (once a day)")
        self.auto_check.toggled.connect(lambda on: self._state.update(check_updates=on))
        check = QPushButton("Check for updates now")
        check.clicked.connect(self._check_now)
        self.update_result = label("", "Hint", wrap=True)
        card.body.addWidget(self.version)
        card.body.addWidget(self.auto_check)
        card.body.addLayout(hbox(check, self.update_result, None))
        return card

    def _build_files(self) -> Card:
        card = Card("Shortcuts & files")
        shortcuts = QPushButton("Add Start menu && desktop shortcuts")  # && = literal &
        shortcuts.clicked.connect(self._add_shortcuts)
        failed = QPushButton("Open failed-tracks log")
        failed.clicked.connect(self._open_failed_log)
        data = QPushButton("Open settings && logs folder")
        data.clicked.connect(lambda: open_path(data_dir()))
        reset = QPushButton("Reset all settings")
        reset.clicked.connect(self._reset)
        card.body.addLayout(hbox(shortcuts, None))
        card.body.addLayout(hbox(failed, data, reset, None))
        return card

    def _build_about(self) -> Card:
        card = Card("About")
        card.body.addWidget(label(DISCLAIMER, "Muted", wrap=True))
        github = QPushButton("Project page")
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        card.body.addLayout(hbox(github, None))
        return card

    # ---- behaviour
    def show_update_result(self, text: str) -> None:
        self.update_result.setText(text)

    def _check_now(self) -> None:
        self.update_result.setText("Checking...")
        self.check_updates_requested.emit()

    def _load(self) -> None:
        s: Settings = self._state.settings
        self.version.setText(f"You have version {APP_VERSION} ({INSTALL_KINDS[install_kind()]}).")
        self.auto_check.blockSignals(True)
        self.auto_check.setChecked(s.check_updates)
        self.auto_check.blockSignals(False)
        self._show_tool(self.ffmpeg_status, self.install_ffmpeg, find_ffmpeg(s),
                        "Not found - nothing can be converted to MP3 until it's installed.")
        self._show_tool(self.node_status, self.install_node, find_js_runtime(),
                        "Not found - YouTube matches won't work until it's installed.")

    @staticmethod
    def _show_tool(status, button, found: str | None, missing: str) -> None:
        status.setText(f"Found: {found}" if found else missing)
        status.setObjectName("Hint" if found else "Warning")
        status.style().polish(status)
        button.setVisible(not found)

    def _choose_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Find ffmpeg.exe", "", "ffmpeg (ffmpeg.exe);;Programs (*.exe)")
        if path:
            self._state.update(ffmpeg_path=os.path.normpath(path))

    def _add_shortcuts(self) -> None:
        created = create_shortcuts(list(shortcut_folders()))
        if created:
            QMessageBox.information(self, "Shortcuts", "Added:\n" + "\n".join(str(p) for p in created))
        else:
            QMessageBox.warning(self, "Shortcuts", "The shortcuts couldn't be created.")

    def _open_failed_log(self) -> None:
        path = failed_log_path(self._state.settings.library)
        if path.exists():
            open_path(path)
        else:
            QMessageBox.information(self, "Failed tracks", "No failed tracks so far.")

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset settings",
            "Put every setting back to its default? Your queue, folders list and library folder are kept.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            current = self._state.settings
            self._state.replace(Settings(
                library=current.library, folders=current.folders, offered_shortcuts=True,
                last_update_check=current.last_update_check,
            ))
