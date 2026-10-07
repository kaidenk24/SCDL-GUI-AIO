"""Table model for the download queue, and the 'Save to' folder picker used inside it."""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from scdl_gui.engine import guess_kind
from scdl_gui.settings import FOLDER_AUTO, FOLDER_ROOT, Job
from scdl_gui.templates import clean_folder_name
from scdl_gui.ui import theme

MIME_ROWS = "application/x-scdl-queue-rows"
COL_ON, COL_NAME, COL_TYPE, COL_FOLDER, COL_STATUS, COL_LINK = range(6)
HEADERS = ("", "Name", "Type", "Save to", "Status", "Link")
AUTO_KEY = "\x00auto"  # QComboBox can't tell None data from "no data"


def folder_label(folder: str | None) -> str:
    if folder is FOLDER_AUTO:
        return "Auto (save layout)"
    if folder == FOLDER_ROOT:
        return "Library folder"
    return folder


def folder_to_key(folder: str | None) -> str:
    return AUTO_KEY if folder is FOLDER_AUTO else folder


def key_to_folder(key: str) -> str | None:
    return FOLDER_AUTO if key == AUTO_KEY else key


def folder_choices(custom_folders: tuple[str, ...]) -> list[tuple[str, str | None]]:
    return [(folder_label(FOLDER_AUTO), FOLDER_AUTO), (folder_label(FOLDER_ROOT), FOLDER_ROOT)] + [
        (f, f) for f in custom_folders
    ]


def _status_color(status: str) -> str:
    if status.startswith("Done"):
        return theme.WARNING if "failed" in status else theme.SUCCESS
    if status.startswith("Failed"):
        return theme.DANGER
    if status.startswith("Stopped"):
        return theme.WARNING
    if status.startswith("Downloading") or status.startswith("Starting"):
        return theme.ACCENT
    return theme.MUTED


def short_link(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url)


class QueueModel(QAbstractTableModel):
    changed = Signal()  # structure or user edits changed (save + recount)

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self._jobs = list(jobs)

    # ---- Qt model interface
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._jobs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job, col = self._jobs[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                COL_NAME: job.name or short_link(job.url),
                COL_TYPE: job.kind or guess_kind(job.url),
                COL_FOLDER: folder_label(job.folder),
                COL_STATUS: job.status,
                COL_LINK: short_link(job.url),
            }.get(col)
        if role == Qt.ItemDataRole.EditRole and col == COL_FOLDER:
            return folder_to_key(job.folder)
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_ON:
            return Qt.CheckState.Checked if job.enabled else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STATUS:
                return QColor(_status_color(job.status))
            if col in (COL_LINK, COL_TYPE) or (col == COL_NAME and not job.name):
                return QColor(theme.MUTED)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_FOLDER:
                return "Click to choose where this link's tracks are saved"
            if col == COL_ON:
                return "Include this link when you press Start"
            return job.url
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        job, col = self._jobs[index.row()], index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_ON:
            job.enabled = Qt.CheckState(value) == Qt.CheckState.Checked
        elif role == Qt.ItemDataRole.EditRole and col == COL_FOLDER:
            job.folder = key_to_folder(value)
        else:
            return False
        self.dataChanged.emit(index, index)
        self.changed.emit()
        return True

    def flags(self, index: QModelIndex):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if index.column() == COL_ON:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == COL_FOLDER:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def mimeTypes(self) -> list[str]:
        return [MIME_ROWS]

    def mimeData(self, indexes) -> QMimeData:
        rows = sorted({i.row() for i in indexes})
        mime = QMimeData()
        mime.setData(MIME_ROWS, ",".join(map(str, rows)).encode())
        return mime

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction

    # ---- queue operations
    @property
    def jobs(self) -> list[Job]:
        return list(self._jobs)

    def job(self, row: int) -> Job:
        return self._jobs[row]

    def add(self, urls: list[str], folder: str | None) -> list[str]:
        """Append links not already queued; returns the ones added."""
        known = {job.url for job in self._jobs}
        fresh = [u for u in urls if u not in known]
        if fresh:
            start = len(self._jobs)
            self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
            self._jobs.extend(Job(url=u, folder=folder, kind=guess_kind(u)) for u in fresh)
            self.endInsertRows()
            self.changed.emit()
        return fresh

    def remove(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._jobs[row]
            self.endRemoveRows()
        self.changed.emit()

    def remove_where(self, predicate: Callable[[Job], bool]) -> None:
        self.remove([row for row, job in enumerate(self._jobs) if predicate(job)])

    def update(self, row: int, **changes) -> None:
        if not 0 <= row < len(self._jobs):
            return
        for key, value in changes.items():
            setattr(self._jobs[row], key, value)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))

    def set_folder(self, rows: list[int], folder: str | None) -> None:
        for row in rows:
            self.update(row, folder=folder)
        self.changed.emit()

    def rows_for_url(self, url: str) -> list[int]:
        return [row for row, job in enumerate(self._jobs) if job.url == url]

    def replace_folder(self, old: str, new: str | None) -> None:
        self.set_folder([row for row, job in enumerate(self._jobs) if job.folder == old], new)

    def folder_counts(self) -> dict:
        counts: dict = {}
        for job in self._jobs:
            counts[job.folder] = counts.get(job.folder, 0) + 1
        return counts


class FolderDelegate(QStyledItemDelegate):
    """Editable drop-down in the 'Save to' column; typing a new name creates that folder."""

    def __init__(self, choices: Callable[[], list], on_new_folder: Callable[[str], None], parent=None) -> None:
        super().__init__(parent)
        self._choices = choices
        self._on_new_folder = on_new_folder

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for text, folder in self._choices():
            combo.addItem(text, folder_to_key(folder))
        combo.activated.connect(lambda _i: (self.commitData.emit(combo), self.closeEditor.emit(combo)))
        return combo

    def setEditorData(self, editor: QComboBox, index) -> None:
        position = editor.findData(index.data(Qt.ItemDataRole.EditRole))
        editor.setCurrentIndex(max(position, 0))
        editor.showPopup()

    def setModelData(self, editor: QComboBox, model, index) -> None:
        text = editor.currentText().strip()
        position = editor.findText(text, Qt.MatchFlag.MatchFixedString)
        if position >= 0:
            model.setData(index, editor.itemData(position), Qt.ItemDataRole.EditRole)
            return
        folder = clean_folder_name(text)
        if folder:
            self._on_new_folder(folder)
            model.setData(index, folder, Qt.ItemDataRole.EditRole)
