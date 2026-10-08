"""Queue page: paste links, choose a folder per link, see each link's status."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from scdl_gui.engine import extract_links
from scdl_gui.ui.folders_panel import FoldersPanel
from scdl_gui.ui.queue_model import (
    COL_FOLDER,
    COL_LINK,
    COL_NAME,
    COL_ON,
    COL_STATUS,
    COL_TYPE,
    FolderDelegate,
    QueueModel,
    folder_choices,
    folder_to_key,
    key_to_folder,
)
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, FlowRow, Page, ResponsiveSplitter, hbox, label

PASTE_HINT = (
    "Paste SoundCloud links here - playlists, albums, your likes, a profile, single tracks or "
    "on.soundcloud.com share links. Any text works; the links are picked out for you."
)


class QueuePage(Page):
    links_added = Signal(list)  # new links, to look up their names
    lookup_requested = Signal(list)
    follow_requested = Signal(list)  # Jobs to follow on the Playlists page

    def __init__(self, state: AppState, model: QueueModel) -> None:
        super().__init__("Queue", "Add links, choose where each one is saved, then press Start.")
        self._state = state
        self._model = model
        self.body.addWidget(self._build_add_card())
        self.body.addWidget(self._build_queue(), 1)
        state.settings_changed.connect(lambda _s: self._refresh_new_link_folders())
        model.changed.connect(self._update_summary)
        model.dataChanged.connect(lambda *_: self._update_summary())
        self._refresh_new_link_folders()
        self._update_summary()

    # ---- building
    def _build_add_card(self) -> Card:
        card = Card("Add links")
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(PASTE_HINT)
        self.paste.setFixedHeight(78)
        add = QPushButton("Add to queue")
        add.setObjectName("Primary")
        add.clicked.connect(self._add_from_box)
        clipboard = QPushButton("Paste from clipboard")
        clipboard.clicked.connect(self._add_from_clipboard)
        import_ = QPushButton("Import .txt...")
        import_.clicked.connect(self._import_file)
        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        for button in (add, clipboard, import_):
            buttons.addWidget(button)
        card.body.addLayout(hbox(self.paste, buttons, spacing=12))

        self.new_link_folder = QComboBox()
        self.new_link_folder.setMinimumWidth(220)
        self.new_link_folder.setToolTip("Where newly added links are saved. You can change each link later.")
        self.new_link_folder.activated.connect(
            lambda _i: self._state.update(new_link_folder=key_to_folder(self.new_link_folder.currentData()))
        )
        self.add_feedback = label("", "Hint")
        card.body.addLayout(hbox(label("New links go to:"), self.new_link_folder, self.add_feedback, None))
        QShortcut(QKeySequence("Ctrl+Return"), self.paste, activated=self._add_from_box)
        return card

    def _build_queue(self) -> ResponsiveSplitter:
        self.table = QTableView()
        self.table.setMinimumHeight(180)
        self.table.setModel(self._model)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.clicked.connect(self._on_click)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(34)
        for col, mode in ((COL_ON, "Fixed"), (COL_NAME, "Stretch"), (COL_TYPE, "ResizeToContents"),
                          (COL_FOLDER, "Interactive"), (COL_STATUS, "Stretch")):
            header.setSectionResizeMode(col, getattr(QHeaderView.ResizeMode, mode))
        self.table.setColumnWidth(COL_ON, 34)
        self.table.setColumnWidth(COL_FOLDER, 170)
        self.table.setColumnHidden(COL_LINK, True)  # shown as the Name tooltip and in the right-click menu
        self.delegate = FolderDelegate(
            lambda: folder_choices(self._state.settings.folders), self._on_new_folder, self.table
        )
        self.table.setItemDelegateForColumn(COL_FOLDER, self.delegate)
        QShortcut(QKeySequence.StandardKey.Delete, self.table, activated=self._remove_selected)

        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        clear_done = QPushButton("Clear finished")
        clear_done.setToolTip("Remove links that downloaded without problems")
        clear_done.clicked.connect(
            lambda: self._model.remove_where(lambda j: j.status.startswith("Done") and "failed" not in j.status)
        )
        clear_all = QPushButton("Clear all")
        clear_all.clicked.connect(lambda: self._model.remove_where(lambda _j: True))
        lookup = QPushButton("Look up names")
        lookup.setToolTip("Fetch playlist names from SoundCloud for links that show only their address")
        lookup.clicked.connect(lambda: self.lookup_requested.emit([j.url for j in self._model.jobs if not j.name]))
        self.summary = label("", "Hint")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(FlowRow(remove, clear_done, clear_all, lookup))
        left_layout.addWidget(self.summary)

        self.folders = FoldersPanel(self._state, self._model)
        self.folders.assign_requested.connect(lambda folder: self._model.set_folder(self.selected_rows(), folder))
        self.folders.setMinimumWidth(210)

        splitter = ResponsiveSplitter(left, self.folders, stack_below=760, wide_sizes=(800, 260), stacked_sizes=(320, 260))
        splitter.setStretchFactor(0, 1)
        return splitter

    # ---- adding links
    def add_links(self, text: str) -> None:
        links = extract_links(text)
        if not links:
            self.add_feedback.setText("No soundcloud.com links found in that text.")
            return
        added = self._model.add(links, self._state.settings.new_link_folder)
        skipped = len(links) - len(added)
        message = f"Added {len(added)} link(s)."
        if skipped:
            message += f" {skipped} already in the queue."
        self.add_feedback.setText(message)
        if added:
            self.links_added.emit(added)

    def _add_from_box(self) -> None:
        self.add_links(self.paste.toPlainText())
        if self.add_feedback.text().startswith("Added"):
            self.paste.clear()

    def _add_from_clipboard(self) -> None:
        self.add_links(QGuiApplication.clipboard().text())

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import links", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                self.add_links(f.read())
        except OSError as err:
            self.add_feedback.setText(f"Couldn't read that file: {err}")

    # ---- table helpers
    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _remove_selected(self) -> None:
        self._model.remove(self.selected_rows())

    def _on_click(self, index: QModelIndex) -> None:
        if index.column() == COL_FOLDER:
            self.table.edit(index)

    def _on_new_folder(self, folder: str) -> None:
        self.folders.add_folder(folder)

    def _context_menu(self, pos) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        menu = QMenu(self)
        move = menu.addMenu("Save to")
        for text, folder in folder_choices(self._state.settings.folders):
            move.addAction(text, lambda f=folder: self._model.set_folder(rows, f))
        menu.addSeparator()
        menu.addAction("Download again", lambda: [self._model.update(r, status="Queued", enabled=True) for r in rows])
        follow = menu.addAction("Follow - download new tracks automatically",
                                lambda: self.follow_requested.emit([self._model.job(r) for r in rows]))
        follow.setEnabled(any(self._model.job(r).kind != "Track" for r in rows))
        menu.addAction("Look up name", lambda: self.lookup_requested.emit([self._model.job(r).url for r in rows]))
        urls = [self._model.job(r).url for r in rows]
        menu.addAction("Open on SoundCloud", lambda: [QDesktopServices.openUrl(QUrl(u)) for u in urls[:5]])
        menu.addAction("Copy link", lambda: QGuiApplication.clipboard().setText("\n".join(urls)))
        menu.addSeparator()
        menu.addAction("Remove", lambda: self._model.remove(rows))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _refresh_new_link_folders(self) -> None:
        self.new_link_folder.clear()
        for text, folder in folder_choices(self._state.settings.folders):
            self.new_link_folder.addItem(text, folder_to_key(folder))
        position = self.new_link_folder.findData(folder_to_key(self._state.settings.new_link_folder))
        self.new_link_folder.setCurrentIndex(max(position, 0))

    def _update_summary(self) -> None:
        jobs = self._model.jobs
        ticked = sum(1 for j in jobs if j.enabled)
        self.summary.setText(f"{len(jobs)} link(s) - {ticked} ticked for download" if jobs else "Queue is empty")
