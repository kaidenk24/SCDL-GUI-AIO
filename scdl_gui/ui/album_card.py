"""'Album tag' card: how the Album tag is set, plus fixing it on MP3s already in the library."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton

from scdl_gui.retag import RETAG_MODES, retag_library
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, OptionList, hbox, label

ALBUM_OPTIONS = [
    ("title", "Album = song title (recommended)",
     "Every song shows its own cover in iTunes, Apple Music and most players. Your folders keep playlists together."),
    ("playlist", "Album = playlist name, with track numbers",
     "Each playlist shows up as one album - but iTunes then uses one cover for all of its songs."),
    ("none", "No album tag", "Players file the songs under 'Unknown album'."),
]


class _Bridge(QObject):
    progress = Signal(int)
    done = Signal(object)  # RetagResult | Exception


class AlbumCard(Card):
    def __init__(self, state: AppState) -> None:
        super().__init__("Album tag", "What the Album field of each MP3 says.")
        self._state = state
        self._busy = False
        self.options = OptionList(ALBUM_OPTIONS)
        self.options.changed.connect(lambda mode: state.update(album_mode=mode))
        self.apply = QPushButton("Apply to MP3s already in my library")
        self.apply.setToolTip("Rewrites only the Album tag of files you already have - the audio isn't touched")
        self.apply.clicked.connect(self._apply)
        self.status = label("", "Hint", wrap=True)
        self.body.addWidget(self.options)
        self.body.addLayout(hbox(self.apply, None))
        self.body.addWidget(self.status)
        self._bridge = _Bridge()
        self._bridge.progress.connect(lambda n: self.status.setText(f"Checked {n} files..."))
        self._bridge.done.connect(self._on_done)
        state.settings_changed.connect(lambda _s: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        mode = self._state.settings.album_mode
        self.options.set_value(mode)
        self.apply.setEnabled(mode in RETAG_MODES and not self._busy)
        self.apply.setToolTip(
            "Rewrites only the Album tag of files you already have - the audio isn't touched" if mode in RETAG_MODES
            else "Playlist albums can only be set while downloading (each file doesn't know its playlist)"
        )

    def _apply(self) -> None:
        library = Path(self._state.settings.library)
        mode = self._state.settings.album_mode
        what = "its song title" if mode == "title" else "empty"
        answer = QMessageBox.question(
            self, "Album tag",
            f"Set the Album tag of every MP3 in\n{library}\nto {what}?\n\n"
            "Only the tags change, not the audio. Best done when no downloads are running.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self.refresh()
        self.status.setText("Working...")

        def work() -> None:
            try:
                self._bridge.done.emit(retag_library(library, mode, self._bridge.progress.emit))
            except Exception as err:  # report instead of dying silently in a thread
                self._bridge.done.emit(err)

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, result) -> None:
        self._busy = False
        self.refresh()
        if isinstance(result, Exception):
            self.status.setText(f"Couldn't update the tags: {result}")
            return
        text = f"Done - {result.changed} file(s) updated, {result.unchanged} already right."
        if result.failed:
            text += f" {len(result.failed)} couldn't be changed (in use?): {result.failed[0]}"
        self.status.setText(text + " In iTunes, re-add the files so it reads the new tags.")
