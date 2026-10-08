"""YouTube matches page: confirm a YouTube replacement for each DRM-protected SoundCloud track."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from yt_dlp.utils import sanitize_filename

from scdl_gui.matches import (
    DOWNLOADING,
    FAILED,
    NEEDS_USER,
    NO_MATCH,
    REVIEW,
    SAVED,
    SEARCHING,
    SKIPPED,
    STATUS_TEXT,
    MatchItem,
    item_key,
    load_matches,
    load_skipped,
    save_matches,
    save_skipped,
)
from scdl_gui.matching import STRONG_MATCH, format_duration
from scdl_gui.runner import MatchDownloadRunner, MatchSearchRunner
from scdl_gui.ui import theme
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, FlowRow, Page, ResponsiveSplitter, hbox, label

STATUS_COLORS = {
    SEARCHING: theme.MUTED, REVIEW: theme.ACCENT, NO_MATCH: theme.WARNING, DOWNLOADING: theme.MUTED,
    SAVED: theme.SUCCESS, SKIPPED: theme.MUTED, FAILED: theme.DANGER,
}
COLUMNS = ("Match", "Title", "Artist / channel", "Length", "Source")


def _score_color(score: int) -> str:
    return theme.SUCCESS if score >= STRONG_MATCH else theme.WARNING if score >= 70 else theme.DANGER


class MatchesPage(Page):
    needs_user_changed = Signal(int)

    def __init__(self, state: AppState) -> None:
        super().__init__(
            "YouTube matches",
            "SoundCloud won't let anyone download DRM-protected tracks, so the app looks for the same song on "
            "YouTube. Check the match (press Listen if unsure) and it's saved where the SoundCloud track would "
            "have gone, with the same name and tags.",
        )
        self._state = state
        self._items: list[MatchItem] = load_matches()
        self._skipped: set[str] = load_skipped()
        self._detail_state: tuple | None = None  # what the detail card shows, to skip needless redraws
        self._candidates_key = ""
        self.searcher = MatchSearchRunner(self)
        self.searcher.found.connect(self._on_found)
        self.downloader = MatchDownloadRunner(self)
        self.downloader.done.connect(self._on_done)

        self.summary = label("", "Muted")
        accept = QPushButton("Accept all strong matches...")
        accept.setToolTip(f"Download the top result for every track whose best match scores {STRONG_MATCH}% or more")
        accept.clicked.connect(self._accept_strong)
        clear = QPushButton("Remove finished")
        clear.clicked.connect(self._remove_finished)
        self.summary.setWordWrap(True)
        top = hbox(self.summary, FlowRow(accept, clear), spacing=16)
        top.setStretch(0, 1)
        self.body.addLayout(top)

        self.list = QListWidget()
        self.list.setObjectName("Folders")
        self.list.setMinimumSize(210, 120)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(lambda _row: self._show_selected())
        splitter = ResponsiveSplitter(self.list, self._build_detail(), stack_below=820,
                                      wide_sizes=(300, 700), stacked_sizes=(150, 500))
        splitter.setStretchFactor(1, 1)
        self.body.addWidget(splitter, 1)

        self._refresh_list()
        QTimer.singleShot(0, self._resume)

    # ---- layout
    def _build_detail(self) -> QWidget:
        card = Card("")
        self.detail_title = card.title
        self.detail_meta = label("", "Muted", wrap=True)
        self.detail_target = label("", "Hint", wrap=True)
        self.detail_target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_sc = QPushButton("Open on SoundCloud")
        open_sc.clicked.connect(lambda: self._open(self._current().track.get("sc_url")) if self._current() else None)
        card.body.addWidget(self.detail_meta)
        card.body.addWidget(self.detail_target)
        card.body.addLayout(hbox(open_sc, None))

        self.candidates = QTreeWidget()
        self.candidates.setHeaderLabels(COLUMNS)
        self.candidates.setRootIsDecorated(False)
        self.candidates.setAlternatingRowColors(True)
        self.candidates.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidates.itemDoubleClicked.connect(lambda item, _c: self._open(item.data(0, Qt.ItemDataRole.UserRole)))
        self.candidates.setMinimumHeight(150)
        header = self.candidates.header()
        header.setStretchLastSection(False)
        for col, mode in ((0, "ResizeToContents"), (1, "Stretch"), (2, "Stretch"), (3, "ResizeToContents"), (4, "ResizeToContents")):
            header.setSectionResizeMode(col, getattr(QHeaderView.ResizeMode, mode))
        card.body.addWidget(label("Matches (best first - double-click to listen):", "CardTitle"))
        card.body.addWidget(self.candidates, 1)

        self.query = QLineEdit()
        self.query.setPlaceholderText("Search words")
        self.query.returnPressed.connect(self._search_again)
        search = QPushButton("Search again")
        search.clicked.connect(self._search_again)
        card.body.addLayout(hbox(label("Search for:"), self.query, search))

        self.listen = QPushButton("Listen on YouTube")
        self.listen.clicked.connect(lambda: self._open(self._selected_candidate_url()))
        self.skip = QPushButton("Skip this track")
        self.skip.clicked.connect(self._skip)
        self.use = QPushButton("Use this match")
        self.use.setObjectName("Primary")
        self.use.clicked.connect(self._use_selected)
        card.body.addLayout(hbox(self.listen, self.skip, None, self.use))
        self.detail_message = label("", "Hint", wrap=True)
        card.body.addWidget(self.detail_message)
        self.detail = card

        self.empty = label(
            "Nothing to check right now.\n\nWhen a playlist has a track SoundCloud won't allow downloading "
            "(DRM), it shows up here with suggested YouTube matches.", "Muted", wrap=True,
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card, 1)
        layout.addWidget(self.empty, 1)
        return holder

    # ---- public
    def add_track(self, track: dict, scheduled: bool = False) -> None:
        """A DRM-protected track to match. scheduled: reported by an automatic check of a followed
        playlist, which reports the same tracks every time - only new ones are added then."""
        key = item_key(track)
        existing = next((i for i in self._items if i.key == key), None)
        if scheduled and (existing is not None or key in self._skipped):
            return
        if existing is not None and existing.status not in (SKIPPED, FAILED):
            return
        if existing is not None:
            self._items.remove(existing)
        if key in self._skipped:  # downloading the playlist yourself asks again
            self._skipped.discard(key)
            save_skipped(self._skipped)
        item = MatchItem(track=track)
        self._items.append(item)
        self._search([item])
        self._changed()

    def needs_user(self) -> int:
        return sum(1 for i in self._items if i.status in NEEDS_USER)

    # ---- searching & downloading
    def _resume(self) -> None:
        waiting = [i for i in self._items if i.status == SEARCHING]
        if waiting:
            self._search(waiting)

    def _search(self, items: list[MatchItem]) -> None:
        for item in items:
            item.status = SEARCHING
        self.searcher.search([{"key": i.key, "track": i.track, "query": i.query} for i in items], self._state.settings)

    def _on_found(self, data: dict) -> None:
        item = self._find(data.get("key"))
        if item is None:
            return
        item.candidates = data.get("candidates") or []
        item.query = data.get("query") or item.query
        item.status = REVIEW if item.candidates else NO_MATCH
        item.message = data.get("error", "") if not item.candidates else ""
        self._changed()

    def _start_download(self, item: MatchItem, url: str) -> None:
        item.status = DOWNLOADING
        item.chosen_url = url
        item.message = ""
        target = item.track.get("target") or str(Path(self._state.settings.library) / sanitize_filename(item.track.get("title") or "track"))
        job = {"key": item.key, "url": url, "target": target, "track": item.track, "archive": item.track.get("archive", "")}
        self.downloader.download(job, self._state.settings)

    def _on_done(self, key: str, ok: bool, message: str) -> None:
        item = self._find(key)
        if item is None:
            return
        item.status = SAVED if ok else FAILED
        item.message = message
        self._changed()

    # ---- user actions
    def _use_selected(self) -> None:
        item, url = self._current(), self._selected_candidate_url()
        if item is None or not url:
            return
        self._start_download(item, url)
        self._changed()

    def _skip(self) -> None:
        item = self._current()
        if item is not None:
            item.status = SKIPPED
            self._skipped.add(item.key)
            save_skipped(self._skipped)
            self._changed()

    def _search_again(self) -> None:
        item = self._current()
        if item is not None:
            item.query = self.query.text().strip()
            item.candidates = []
            self._search([item])
            self._changed()

    def _accept_strong(self) -> None:
        strong = [i for i in self._items if i.status == REVIEW and i.candidates and i.candidates[0]["score"] >= STRONG_MATCH]
        if not strong:
            QMessageBox.information(self, "YouTube matches", f"No tracks have a {STRONG_MATCH}%+ match waiting.")
            return
        names = "\n".join(f"- {i.label}  ->  {i.candidates[0]['title']} ({i.candidates[0]['score']}%)" for i in strong[:15])
        more = f"\n...and {len(strong) - 15} more" if len(strong) > 15 else ""
        answer = QMessageBox.question(self, "Accept strong matches", f"Download these {len(strong)} match(es)?\n\n{names}{more}")
        if answer == QMessageBox.StandardButton.Yes:
            for item in strong:
                self._start_download(item, item.candidates[0]["url"])
            self._changed()

    def _remove_finished(self) -> None:
        self._items = [i for i in self._items if i.status not in (SAVED, SKIPPED)]
        self._changed()

    # ---- display
    def _changed(self) -> None:
        save_matches(self._items)
        self._refresh_list()
        self.needs_user_changed.emit(self.needs_user())

    def _refresh_list(self) -> None:
        """Update the list in place: rows keep their position, and the selection and scroll position stay
        where they are when another track's status changes (rebuilding the list made it jump)."""
        current = self._current()
        self.list.blockSignals(True)
        wanted = [item.key for item in self._items]
        for row in reversed(range(self.list.count())):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) not in wanted:
                self.list.takeItem(row)
        for row, item in enumerate(self._items):
            entry = self.list.item(row)
            if entry is None or entry.data(Qt.ItemDataRole.UserRole) != item.key:
                entry = QListWidgetItem()
                entry.setData(Qt.ItemDataRole.UserRole, item.key)
                self.list.insertItem(row, entry)
            playlist = item.track.get("playlist") or "single track"
            text = f"{item.label}\n{playlist}  -  {STATUS_TEXT.get(item.status, item.status)}"
            if entry.text() != text:
                entry.setText(text)
                entry.setToolTip(item.label)
                entry.setForeground(QColor(STATUS_COLORS.get(item.status, theme.TEXT)))
        if self.list.currentItem() is None and self._items:
            first_open = next((n for n, i in enumerate(self._items) if i.status in NEEDS_USER), 0)
            self.list.setCurrentRow(first_open)
        self.list.blockSignals(False)
        counts = {s: sum(1 for i in self._items if i.status == s) for s in STATUS_TEXT}
        self.summary.setText(
            f"{self.needs_user()} waiting for you  -  {counts[SEARCHING]} searching  -  "
            f"{counts[DOWNLOADING]} downloading  -  {counts[SAVED]} saved" if self._items else ""
        )
        shown = self._current()
        if shown is None or current is None or shown.key != current.key or self._detail_state != self._state_of(shown):
            self._show_selected()

    @staticmethod
    def _state_of(item: MatchItem) -> tuple:
        return item.key, item.status, item.query, item.chosen_url, item.message, len(item.candidates)

    def _show_selected(self) -> None:
        item = self._current()
        self.detail.setVisible(item is not None)
        self.empty.setVisible(item is None)
        self._detail_state = self._state_of(item) if item is not None else None
        if item is None:
            return
        track = item.track
        self.detail_title.setText(track.get("title") or "?")
        bits = [f"SoundCloud: {track.get('uploader') or '?'}", format_duration(track.get("duration"))]
        if track.get("playlist"):
            bits.append(f"playlist '{track['playlist']}' #{track.get('playlist_index') or '?'}")
        if track.get("isrc"):
            bits.append(f"ISRC {track['isrc']}")
        self.detail_meta.setText("  -  ".join(bits))
        prefix = "Saved as" if item.status == SAVED else "Will be saved as"
        self.detail_target.setText(f"{prefix}: {track.get('target') or '(library folder)'}.mp3")
        self.query.setText(item.query)
        self._fill_candidates(item)
        busy = item.status in (SEARCHING, DOWNLOADING)
        self.use.setEnabled(bool(item.candidates) and not busy and item.status != SAVED)
        self.skip.setEnabled(item.status not in (SAVED, SKIPPED, DOWNLOADING))
        message = {SEARCHING: "Searching YouTube...", DOWNLOADING: "Downloading..."}.get(item.status, item.message)
        if item.status == SAVED:
            message = f"Saved {item.message}."
        elif item.status == NO_MATCH and not message:
            message = "Nothing similar found. Try different search words above."
        self.detail_message.setText(message)

    def _fill_candidates(self, item: MatchItem) -> None:
        picked = self._selected_candidate_url() if item.key == self._candidates_key else ""
        self._candidates_key = item.key
        self.candidates.clear()
        source_length = item.track.get("duration")
        for cand in item.candidates:
            length = format_duration(cand.get("duration"))
            if source_length and cand.get("duration"):
                diff = cand["duration"] - source_length
                length += f"  ({diff:+d}s)" if diff else "  (same)"
            row = QTreeWidgetItem([f"{cand['score']}%", cand["title"], cand.get("channel", ""), length, cand.get("source", "")])
            row.setForeground(0, QColor(_score_color(cand["score"])))
            row.setData(0, Qt.ItemDataRole.UserRole, cand["url"])
            row.setToolTip(1, cand["url"])
            if cand["url"] == item.chosen_url:
                row.setText(1, f"{cand['title']}   (chosen)")
            self.candidates.addTopLevelItem(row)
            if cand["url"] == picked:
                self.candidates.setCurrentItem(row)
        if self.candidates.currentItem() is None and self.candidates.topLevelItemCount():
            self.candidates.setCurrentItem(self.candidates.topLevelItem(0))

    # ---- helpers
    def _current(self) -> MatchItem | None:
        entry = self.list.currentItem()
        return self._find(entry.data(Qt.ItemDataRole.UserRole)) if entry else None

    def _find(self, key: str | None) -> MatchItem | None:
        return next((i for i in self._items if i.key == key), None)

    def _selected_candidate_url(self) -> str:
        row = self.candidates.currentItem()
        return row.data(0, Qt.ItemDataRole.UserRole) if row else ""

    @staticmethod
    def _open(url: str | None) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))
