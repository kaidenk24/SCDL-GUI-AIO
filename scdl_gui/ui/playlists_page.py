"""Playlists page: follow playlists, each saved to its own folder, and download new tracks automatically."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
)

from scdl_gui.engine import extract_links, guess_kind
from scdl_gui.settings import WATCH_INTERVALS
from scdl_gui.system import set_start_with_windows
from scdl_gui.ui import theme
from scdl_gui.ui.folders_panel import ask_new_folder, ask_other_location, resolve_folder
from scdl_gui.ui.queue_model import FolderDelegate, folder_choices, folder_label, folder_to_key, key_to_folder, short_link
from scdl_gui.ui.state import AppState
from scdl_gui.ui.watch_controller import WatchController
from scdl_gui.ui.widgets import Card, FlowRow, Page, hbox, label
from scdl_gui.watches import Watch, describe_age, describe_wait, next_check_at

COL_ON, COL_NAME, COL_FOLDER, COL_CHECKED, COL_RESULT = range(5)
HEADERS = ("", "Playlist", "Save to", "Last checked", "Last result")
NEW_FOLDER_KEY, OTHER_LOCATION_KEY = "\x00new", "\x00other"
REFRESH_MS = 30_000  # keeps "5 min ago" / "next check in ..." current


def interval_label(hours: int) -> str:
    return "day" if hours == 24 else "hour" if hours == 1 else f"{hours} hours"


class WatchModel(QAbstractTableModel):
    def __init__(self, controller: WatchController) -> None:
        super().__init__()
        self._controller = controller
        self._watches: list[Watch] = controller.watches
        self._live = [controller.live_status(w.url) for w in self._watches]
        controller.changed.connect(self.sync)

    def sync(self) -> None:
        """Pick up changes without resetting the view (keeps selection, scroll position and a 'Save to'
        cell being edited) unless playlists were added or removed."""
        fresh = self._controller.watches
        live = [self._controller.live_status(w.url) for w in fresh]
        if [w.url for w in fresh] != [w.url for w in self._watches]:
            self.beginResetModel()
            self._watches, self._live = fresh, live
            self.endResetModel()
            return
        old, old_live = self._watches, self._live
        self._watches, self._live = fresh, live
        for row, (before, after) in enumerate(zip(old, fresh)):
            if before.folder != after.folder:
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))
            elif before != after or old_live[row] != live[row]:
                self.dataChanged.emit(self.index(row, COL_CHECKED), self.index(row, COL_RESULT))
                self.dataChanged.emit(self.index(row, COL_ON), self.index(row, COL_NAME))

    def tick_clock(self) -> None:
        """'5 min ago' moves on by itself."""
        if self._watches:
            self.dataChanged.emit(self.index(0, COL_CHECKED), self.index(len(self._watches) - 1, COL_CHECKED))

    def watch(self, row: int) -> Watch:
        return self._watches[row]

    # ---- Qt model interface
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._watches)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        watch, col = self._watches[index.row()], index.column()
        live = self._controller.live_status(watch.url)
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                COL_NAME: watch.name or short_link(watch.url),
                COL_FOLDER: folder_label(watch.folder),
                COL_CHECKED: describe_age(watch.last_checked, time.time()),
                COL_RESULT: live or (watch.last_result if watch.enabled else "Paused") or "Not checked yet",
            }.get(col)
        if role == Qt.ItemDataRole.EditRole and col == COL_FOLDER:
            return folder_to_key(watch.folder)
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_ON:
            return Qt.CheckState.Checked if watch.enabled else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_RESULT:
                return QColor(self._result_color(watch, live))
            if col == COL_CHECKED or (col == COL_NAME and not watch.name) or not watch.enabled:
                return QColor(theme.MUTED)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_ON:
                return "Check this playlist automatically (untick to pause)"
            if col == COL_FOLDER:
                return "Click to choose where this playlist's tracks are saved"
            if col == COL_RESULT and watch.total_new:
                return f"{watch.total_new} track(s) downloaded automatically since you followed it"
            return watch.url
        return None

    @staticmethod
    def _result_color(watch: Watch, live: str) -> str:
        if live:
            return theme.ACCENT
        if not watch.enabled:
            return theme.MUTED
        if watch.last_result.startswith("Failed") or "failed" in watch.last_result:
            return theme.DANGER
        if "new" in watch.last_result or "match" in watch.last_result:
            return theme.SUCCESS
        return theme.MUTED

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        watch, col = self._watches[index.row()], index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_ON:
            self._controller.update_watch(watch.url, enabled=Qt.CheckState(value) == Qt.CheckState.Checked)
        elif role == Qt.ItemDataRole.EditRole and col == COL_FOLDER:
            self._controller.update_watch(watch.url, folder=key_to_folder(value))
        else:
            return False
        return True

    def flags(self, index: QModelIndex):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_ON:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == COL_FOLDER:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags


class PlaylistsPage(Page):
    def __init__(self, state: AppState, controller: WatchController) -> None:
        super().__init__(
            "Playlists",
            "Followed playlists keep themselves up to date: new tracks are downloaded into the folder you chose.",
        )
        self._state = state
        self._controller = controller
        self._model = WatchModel(controller)
        self.body.addWidget(self._build_add_card())
        self.body.addWidget(self._build_list_card(), 1)
        self.body.addWidget(self._build_schedule_card())

        controller.changed.connect(self._update_summary)
        controller.running_changed.connect(lambda _running: self._update_summary())
        state.settings_changed.connect(lambda _s: (self._refresh_folders(), self._show_settings(), self._update_summary()))
        self._clock = QTimer(self, interval=REFRESH_MS, timeout=self._model.tick_clock)
        self._clock.timeout.connect(self._update_summary)
        self._clock.start()
        self._refresh_folders()
        self._show_settings()
        self._update_summary()

    # ---- building
    def _build_add_card(self) -> Card:
        card = Card("Follow a playlist")
        self.link = QLineEdit()
        self.link.setPlaceholderText("Paste a SoundCloud playlist, album, likes or profile link (or several)")
        self.link.returnPressed.connect(self._follow)
        self.folder = QComboBox()
        self.folder.setMinimumWidth(170)
        self.folder.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.folder.setMinimumContentsLength(14)
        self.folder.activated.connect(self._on_folder_picked)
        follow = QPushButton("Follow")
        follow.setObjectName("Primary")
        follow.clicked.connect(self._follow)
        card.body.addLayout(hbox(self.link, label("Save to:"), self.folder, follow))
        self.feedback = label(
            "The first check downloads what you don't have yet; after that only tracks added to the playlist.",
            "Hint", wrap=True,
        )
        card.body.addWidget(self.feedback)
        return card

    def _build_list_card(self) -> Card:
        card = Card("Followed")
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(150)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.clicked.connect(lambda index: index.column() == COL_FOLDER and self.table.edit(index))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(34)
        for col, mode in ((COL_ON, "Fixed"), (COL_NAME, "Stretch"), (COL_FOLDER, "Interactive"),
                          (COL_CHECKED, "ResizeToContents"), (COL_RESULT, "Stretch")):
            header.setSectionResizeMode(col, getattr(QHeaderView.ResizeMode, mode))
        self.table.setColumnWidth(COL_ON, 34)
        self.table.setColumnWidth(COL_FOLDER, 170)
        self.delegate = FolderDelegate(lambda: folder_choices(self._state.settings.folders), self._add_folder, self.table)
        self.table.setItemDelegateForColumn(COL_FOLDER, self.delegate)

        check = QPushButton("Check now")
        check.setToolTip("Look for new tracks now (the selected playlists, or all of them)")
        check.clicked.connect(lambda: self._controller.check_now(self._selected_urls() or None))
        unfollow = QPushButton("Unfollow")
        unfollow.setToolTip("Stop following the selected playlists. Downloaded files are not touched.")
        unfollow.clicked.connect(self._unfollow)
        open_ = QPushButton("Open folder")
        open_.clicked.connect(self._open_folder)
        self.summary = label("", "Hint", wrap=True)
        self.empty = label("Nothing followed yet. Paste a playlist link above, or right-click links on the Queue "
                           "page and choose Follow.", "Muted", wrap=True)
        self.interval = QComboBox()
        for hours in WATCH_INTERVALS:
            self.interval.addItem(interval_label(hours), hours)
        self.interval.activated.connect(lambda _i: self._state.update(watch_interval_hours=self.interval.currentData()))
        card.body.addWidget(self.table, 1)
        card.body.addWidget(self.empty)
        card.body.addLayout(hbox(FlowRow(check, unfollow, open_), None, label("Check every"), self.interval))
        card.body.addWidget(self.summary)
        return card

    def _build_schedule_card(self) -> Card:
        card = Card("When the window is closed")
        self.background = QCheckBox("Keep checking from the notification area (the icons by the clock)")
        self.background.toggled.connect(lambda on: self._state.update(run_in_background=on))
        self.startup = QCheckBox("Start with Windows (in the notification area, no window)")
        self.startup.toggled.connect(self._set_startup)
        card.body.addWidget(self.background)
        card.body.addWidget(self.startup)
        card.body.addWidget(label("Checks only happen while the app is running. Right-click the notification-area "
                                  "icon to quit it.", "Hint", wrap=True))
        return card

    # ---- adding
    def _follow(self) -> None:
        links = extract_links(self.link.text())
        if not links:
            self.feedback.setText("No soundcloud.com link found in that text.")
            return
        singles = [u for u in links if guess_kind(u) == "Track"]
        added = self._controller.follow([u for u in links if u not in singles], self._current_folder())
        parts = [f"Following {len(added)} link(s) - the first check starts shortly." if added else "Already following that."]
        if singles:
            parts.append(f"{len(singles)} single track link(s) skipped - add those on the Queue page.")
        self.feedback.setText(" ".join(parts))
        if added:
            self.link.clear()

    def _current_folder(self) -> str | None:
        return key_to_folder(self.folder.currentData())

    def _refresh_folders(self) -> None:
        keep = self.folder.currentData() if self.folder.count() else folder_to_key(self._state.settings.new_link_folder)
        self.folder.blockSignals(True)
        self.folder.clear()
        for text, folder in folder_choices(self._state.settings.folders):
            self.folder.addItem(text, folder_to_key(folder))
        self.folder.insertSeparator(self.folder.count())
        self.folder.addItem("New folder...", NEW_FOLDER_KEY)
        self.folder.addItem("Other location...", OTHER_LOCATION_KEY)
        self.folder.setCurrentIndex(max(self.folder.findData(keep), 0))
        self.folder.blockSignals(False)
        self._last_folder_key = self.folder.currentData()

    def _on_folder_picked(self, _index: int) -> None:
        key = self.folder.currentData()
        if key not in (NEW_FOLDER_KEY, OTHER_LOCATION_KEY):
            self._last_folder_key = key
            return
        folder = ask_new_folder(self) if key == NEW_FOLDER_KEY else ask_other_location(self, self._state.settings.library)
        if folder:
            self._add_folder(folder)
            self.folder.setCurrentIndex(max(self.folder.findData(folder), 0))
            self._last_folder_key = folder
        else:
            self.folder.setCurrentIndex(max(self.folder.findData(self._last_folder_key), 0))

    def _add_folder(self, folder: str) -> None:
        if folder and folder not in self._state.settings.folders:
            self._state.update(folders=(*self._state.settings.folders, folder))

    # ---- list actions
    def _selected_urls(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self._model.watch(r).url for r in rows]

    def _unfollow(self) -> None:
        urls = self._selected_urls()
        if not urls:
            return
        answer = QMessageBox.question(
            self, "Unfollow", f"Stop following {len(urls)} playlist(s)?\nFiles you already downloaded stay where they are.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.unfollow(urls)

    def _open_folder(self) -> None:
        urls = self._selected_urls()
        watch = next((w for w in self._controller.watches if w.url in urls), None)
        path = resolve_folder(self._state.settings.library, watch.folder if watch else "")
        if path.is_dir():
            os.startfile(path)  # noqa: S606 - opening a folder in Explorer
        else:
            QMessageBox.information(self, "Open folder", f"{path}\n\ndoesn't exist yet. It's created by the first download.")

    def _context_menu(self, pos) -> None:
        urls = self._selected_urls()
        if not urls:
            return
        menu = QMenu(self)
        menu.addAction("Check now", lambda: self._controller.check_now(urls))
        move = menu.addMenu("Save to")
        for text, folder in folder_choices(self._state.settings.folders):
            move.addAction(text, lambda f=folder: [self._controller.update_watch(u, folder=f) for u in urls])
        menu.addAction("Open folder", self._open_folder)
        menu.addSeparator()
        menu.addAction("Open on SoundCloud", lambda: [QDesktopServices.openUrl(QUrl(u)) for u in urls[:5]])
        menu.addAction("Copy link", lambda: QGuiApplication.clipboard().setText("\n".join(urls)))
        menu.addSeparator()
        menu.addAction("Unfollow", self._unfollow)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---- settings & summary
    def _show_settings(self) -> None:
        settings = self._state.settings
        for widget, apply in (
            (self.interval, lambda: self.interval.setCurrentIndex(max(self.interval.findData(settings.watch_interval_hours), 0))),
            (self.background, lambda: self.background.setChecked(settings.run_in_background)),
            (self.startup, lambda: self.startup.setChecked(settings.start_with_windows)),
        ):
            widget.blockSignals(True)
            apply()
            widget.blockSignals(False)

    def _set_startup(self, enabled: bool) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = set_start_with_windows(enabled)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if ok:
            self._state.update(start_with_windows=enabled)
        else:
            QMessageBox.warning(self, "Start with Windows", "Windows didn't let the app change its startup shortcut.")
            self._show_settings()

    def _update_summary(self) -> None:
        watches = self._controller.watches
        self.table.setVisible(bool(watches))
        self.empty.setVisible(not watches)
        if not watches:
            self.summary.setText("")
            return
        enabled = sum(1 for w in watches if w.enabled)
        new = sum(w.total_new for w in watches)
        parts = [f"{len(watches)} followed" + (f" ({len(watches) - enabled} paused)" if enabled < len(watches) else "")]
        if new:
            parts.append(f"{new} track(s) downloaded automatically so far")
        problem = self._controller.problem()
        if self._controller.is_running():
            parts.append("checking now...")
        elif problem:
            parts.append(problem)
        else:
            now = time.time()
            due = next_check_at(watches, self._state.settings.watch_interval_hours, now)
            if due is not None:
                parts.append(f"next check {describe_wait(due - now)}")
        self.summary.setText("  -  ".join(parts))
