"""'YouTube Music Premium audio' card on the Setup page: automatic PO tokens."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QMessageBox, QPushButton

from scdl_gui import potoken
from scdl_gui.ui.potoken_manager import PotManager
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, hbox, label

PROJECT_URL = f"https://github.com/{potoken.REPO}"


class PotCard(Card):
    def __init__(self, state: AppState) -> None:
        super().__init__(
            "YouTube Music Premium audio (PO tokens)",
            "With YouTube Music Premium, YouTube matches download at 256k AAC / 282k Opus instead of ~140k. "
            "This sets up a free token generator (bgutil-ytdlp-pot-provider, GPL-3.0) that runs through "
            "Node.js. It's about 100 MB and takes a minute or two; after that it updates itself.",
        )
        self._state = state
        self.manager = PotManager(state, self)
        self.manager.progress.connect(self._on_progress)
        self.manager.finished.connect(self._on_finished)

        self.status = label("", wrap=True)
        self.use = QCheckBox("Use automatic PO tokens for YouTube matches")
        self.use.toggled.connect(lambda on: state.update(auto_po_token=on))
        self.setup = QPushButton("Set up automatic PO tokens")
        self.setup.setObjectName("Primary")
        self.setup.clicked.connect(self._setup)
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self._remove)
        about = QPushButton("About the generator")
        about.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        self.progress = label("", "Hint", wrap=True)
        self.body.addWidget(self.status)
        self.body.addWidget(self.use)
        self.body.addLayout(hbox(self.setup, self.remove, about, None))
        self.body.addWidget(self.progress)
        state.settings_changed.connect(lambda _s: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        install = potoken.installed()
        busy = self.manager.is_busy()
        has_node = self.manager.node() is not None
        if install:
            self.status.setText(f"Ready - generator {install.version}. Premium audio is used for YouTube matches.")
        elif not has_node:
            self.status.setText("Needs Node.js - install it in Helper programs above first.")
        else:
            self.status.setText("Not set up yet.")
        self.use.blockSignals(True)
        self.use.setChecked(self._state.settings.auto_po_token)
        self.use.blockSignals(False)
        self.use.setVisible(install is not None)
        self.setup.setText("Update / reinstall" if install else "Set up automatic PO tokens")
        self.setup.setEnabled(has_node and not busy)
        self.remove.setVisible(install is not None)
        self.remove.setEnabled(not busy)

    def _setup(self) -> None:
        self.progress.setText("Starting...")
        self.manager.setup()
        self.refresh()

    def _remove(self) -> None:
        answer = QMessageBox.question(self, "PO tokens", "Remove the automatic PO-token generator?")
        if answer == QMessageBox.StandardButton.Yes:
            self.manager.remove()

    def _on_progress(self, text: str) -> None:
        self.progress.setText(text)

    def _on_finished(self, ok: bool, message: str) -> None:
        self.progress.setText(message)
        if not ok:
            QMessageBox.warning(self, "PO tokens", f"Setting up automatic PO tokens failed:\n\n{message}")
        self.refresh()
