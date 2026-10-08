"""The 'Folders' side panel on the Queue page: make folders and send links into them."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scdl_gui.settings import FOLDER_AUTO, FOLDER_ROOT
from scdl_gui.templates import clean_folder_name
from scdl_gui.ui.queue_model import MIME_ROWS, QueueModel, folder_choices, folder_to_key, key_to_folder
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import FlowRow, label

NEW_FOLDER_HINT = (
    "Folder name inside your library.\n"
    "Use \\ for subfolders (Gym\\Warm-up) and tokens like {playlist} to keep\n"
    "one subfolder per playlist inside it (Gym\\{playlist})."
)


def resolve_folder(library: str, folder: str | None) -> Path:
    """Real folder on disk for a 'Save to' choice (up to the first {token})."""
    if not folder:
        return Path(library)
    fixed = re.split(r"\{", folder, maxsplit=1)[0].rstrip("\\/")
    return Path(fixed) if Path(fixed).drive else Path(library) / fixed


def ask_new_folder(parent: QWidget) -> str:
    """Name of a new folder inside the library, or "" if cancelled."""
    name, ok = QInputDialog.getText(parent, "New folder", NEW_FOLDER_HINT)
    return clean_folder_name(name) if ok else ""


def ask_other_location(parent: QWidget, start: str) -> str:
    """Any folder on the computer, or "" if cancelled."""
    path = QFileDialog.getExistingDirectory(parent, "Save into this folder", start)
    return os.path.normpath(path) if path else ""


class FolderList(QListWidget):
    """Accepts queue rows dragged from the table."""

    rows_dropped = Signal(list, object)  # rows, folder

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Folders")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_ROWS):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.mimeData().hasFormat(MIME_ROWS):
            self.setCurrentItem(item)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return
        rows = [int(r) for r in bytes(event.mimeData().data(MIME_ROWS)).decode().split(",") if r]
        self.rows_dropped.emit(rows, key_to_folder(item.data(Qt.ItemDataRole.UserRole)))
        event.acceptProposedAction()


class FoldersPanel(QWidget):
    assign_requested = Signal(object)  # folder value for the selected queue rows

    def __init__(self, state: AppState, model: QueueModel) -> None:
        super().__init__()
        self._state = state
        self._model = model
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(label("Folders", "CardTitle"))
        layout.addWidget(label("Drag links onto a folder, or select links and press Send.", "Hint", wrap=True))

        self.list = FolderList()
        self.list.rows_dropped.connect(lambda rows, folder: self._model.set_folder(rows, folder))
        self.list.itemDoubleClicked.connect(lambda _item: self._rename())
        self.list.setMinimumHeight(110)
        layout.addWidget(self.list, 1)

        send = QPushButton("Send selected links here")
        send.setToolTip("Put the links selected in the queue into this folder")
        send.clicked.connect(lambda: self.assign_requested.emit(self.selected_folder()))
        layout.addWidget(send)

        new, pick = QPushButton("New folder..."), QPushButton("Other location...")
        new.setToolTip("Create a folder inside your library")
        pick.setToolTip("Save into any folder on your computer, outside the library")
        new.clicked.connect(self._new_folder)
        pick.clicked.connect(self._pick_location)
        layout.addWidget(FlowRow(new, pick))

        rename, delete, open_ = QPushButton("Rename"), QPushButton("Delete"), QPushButton("Open")
        rename.clicked.connect(self._rename)
        delete.clicked.connect(self._delete)
        open_.clicked.connect(self._open)
        open_.setToolTip("Open this folder in File Explorer")
        layout.addWidget(FlowRow(rename, delete, open_))

        state.settings_changed.connect(lambda _s: self.refresh())
        model.changed.connect(self.refresh)
        self.refresh()

    # ---- list
    def refresh(self) -> None:
        current = self.selected_folder() if self.list.currentItem() else FOLDER_AUTO
        counts = self._model.folder_counts()
        self.list.clear()
        for text, folder in folder_choices(self._state.settings.folders):
            count = counts.get(folder, 0)
            item = QListWidgetItem(f"{text}   ({count})" if count else text)
            item.setData(Qt.ItemDataRole.UserRole, folder_to_key(folder))
            item.setToolTip(self._describe(folder))
            self.list.addItem(item)
            if folder == current:
                self.list.setCurrentItem(item)

    def selected_folder(self) -> str | None:
        item = self.list.currentItem()
        return key_to_folder(item.data(Qt.ItemDataRole.UserRole)) if item else FOLDER_AUTO

    def _describe(self, folder: str | None) -> str:
        if folder is FOLDER_AUTO:
            return "Uses the folder layout from the Save layout page (default: one folder per playlist)"
        if folder == FOLDER_ROOT:
            return "Straight into the library folder, no subfolder"
        return str(self.resolve(folder))

    def resolve(self, folder: str | None) -> Path:
        return resolve_folder(self._state.settings.library, folder)

    # ---- actions
    def add_folder(self, name: str) -> None:
        name = clean_folder_name(name)
        if name and name not in self._state.settings.folders:
            self._state.update(folders=(*self._state.settings.folders, name))
        self._select(name)

    def _select(self, folder: str | None) -> None:
        for i in range(self.list.count()):
            if key_to_folder(self.list.item(i).data(Qt.ItemDataRole.UserRole)) == folder:
                self.list.setCurrentRow(i)

    def _new_folder(self) -> None:
        name = ask_new_folder(self)
        if name:
            self.add_folder(name)

    def _pick_location(self) -> None:
        path = ask_other_location(self, self._state.settings.library)
        if path:
            self.add_folder(path)

    def _custom_selected(self) -> str | None:
        folder = self.selected_folder()
        if folder in (FOLDER_AUTO, FOLDER_ROOT):
            QMessageBox.information(self, "Folders", "Pick one of your own folders first (not Auto or Library folder).")
            return None
        return folder

    def _rename(self) -> None:
        folder = self._custom_selected()
        if folder is None:
            return
        name, ok = QInputDialog.getText(self, "Rename folder", NEW_FOLDER_HINT, text=folder)
        name = clean_folder_name(name) if ok else ""
        if not name or name == folder:
            return
        folders = tuple(name if f == folder else f for f in self._state.settings.folders)
        self._state.update(folders=tuple(dict.fromkeys(folders)))
        self._model.replace_folder(folder, name)
        self._select(name)

    def _delete(self) -> None:
        folder = self._custom_selected()
        if folder is None:
            return
        used = self._model.folder_counts().get(folder, 0)
        if used:
            answer = QMessageBox.question(
                self, "Delete folder",
                f"{used} link(s) are set to '{folder}'. They'll go back to Auto.\n"
                "Files already downloaded are not touched.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._model.replace_folder(folder, FOLDER_AUTO)
        self._state.update(folders=tuple(f for f in self._state.settings.folders if f != folder))

    def _open(self) -> None:
        path = self.resolve(self.selected_folder())
        if path.is_dir():
            os.startfile(path)  # noqa: S606 - opening a folder in Explorer
        else:
            QMessageBox.information(self, "Open folder", f"{path}\n\ndoesn't exist yet. It's created by the first download.")
