"""Activity page: a readable log of what the downloads are doing."""

from __future__ import annotations

import html
import time
from collections import deque

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QPushButton

from scdl_gui.ui import theme
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Page, hbox

MAX_ENTRIES = 20000


class ActivityPage(Page):
    def __init__(self, state: AppState) -> None:
        super().__init__("Activity", "Everything the downloader is doing. Green = saved, grey = already had, red = failed.", scroll=False)
        self._state = state
        self._entries: deque[tuple[str, str, str]] = deque(maxlen=MAX_ENTRIES)

        self.details = QCheckBox("Show technical details")
        self.details.setToolTip("Also show the raw output from scdl/yt-dlp (useful when something goes wrong)")
        self.details.setChecked(state.settings.show_details)
        self.details.toggled.connect(self._toggle_details)
        copy = QPushButton("Copy log")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._plain_text()))
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        self.body.addLayout(hbox(self.details, None, copy, clear))

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_ENTRIES)
        self.view.setStyleSheet('font-family: "Cascadia Mono", "Consolas"; font-size: 9.5pt;')
        self.body.addWidget(self.view, 1)

    def add(self, level: str, text: str) -> None:
        entry = (time.strftime("%H:%M:%S"), level, text)
        self._entries.append(entry)
        if level != "detail" or self.details.isChecked():
            self._render(entry)

    def clear(self) -> None:
        self._entries.clear()
        self.view.clear()

    def _render(self, entry: tuple[str, str, str]) -> None:
        stamp, level, text = entry
        color = theme.LEVEL_COLORS.get(level, theme.TEXT)
        weight = "600" if level == "info" and text.startswith(">") else "400"
        self.view.appendHtml(
            f'<span style="color:#A39B91">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}; font-weight:{weight}">{html.escape(text)}</span>'
        )

    def _toggle_details(self, on: bool) -> None:
        self._state.update(show_details=on)
        self.view.clear()
        for entry in self._entries:
            if entry[1] != "detail" or on:
                self._render(entry)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _plain_text(self) -> str:
        show_details = self.details.isChecked()
        return "\n".join(f"{s}  {t}" for s, level, t in self._entries if level != "detail" or show_details)
