"""Checks followed playlists on a schedule and downloads their new tracks (see watches.py)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from scdl_gui.engine import find_ffmpeg
from scdl_gui.parsing import JobCounts
from scdl_gui.runner import DownloadRunner
from scdl_gui.ui.state import AppState
from scdl_gui.watches import Watch, add_watches, is_due, load_watches, record_check, save_watches

TICK_MS = 60_000  # how often the schedule is looked at
FIRST_TICK_MS = 20_000  # after start-up, let the login check and update check go first
AFTER_YOUR_RUN_MS = 3_000  # a check that was waiting for your downloads starts this soon after
WAITING = "Waiting..."
CHECKING = "Checking..."
logger = logging.getLogger(__name__)


class WatchController(QObject):
    """Owns the followed playlists. Checks never overlap a download you started yourself (`your_runner`):
    a running check steps aside when you start one, and checks wait until yours is done."""

    changed = Signal()  # the list, or a playlist's state, changed
    live_changed = Signal(str)  # url whose running-check status changed (see live_status)
    status = Signal(str)  # what's happening, for the bottom bar
    new_tracks = Signal(str, int)  # playlist name, tracks downloaded by a check
    names_needed = Signal(list)  # newly followed links without a name yet
    log = Signal(str, str)  # level, text (for the Activity page)
    drm_found = Signal(dict)

    def __init__(self, state: AppState, your_runner: DownloadRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._your_runner = your_runner
        your_runner.started.connect(self.pause)  # a running check steps aside; it runs again afterwards
        your_runner.finished.connect(lambda *_: QTimer.singleShot(AFTER_YOUR_RUN_MS, self.tick))
        self._watches: list[Watch] = load_watches()
        self._live: dict[str, str] = {}  # url -> what a running check is doing right now
        self._forced: set[str] = set()  # "Check now" requests that haven't run yet
        self._run_urls: list[str] = []  # links of the current run, by runner row
        self._run_done: set[str] = set()  # links of the current run that finished
        self._problem = ""

        self.runner = DownloadRunner(self)
        self.runner.job_started.connect(self._on_job_started)
        self.runner.job_progress.connect(self._on_job_progress)
        self.runner.job_named.connect(lambda row, name: self.set_name(self._url(row), name))
        self.runner.job_finished.connect(self._on_job_finished)
        self.runner.finished.connect(self._on_run_finished)
        self.runner.log.connect(self.log)
        self.runner.drm_found.connect(self.drm_found)

        self._timer = QTimer(self, interval=TICK_MS, timeout=self.tick)
        self._timer.start()
        QTimer.singleShot(FIRST_TICK_MS, self.tick)

    # ---- reading
    @property
    def watches(self) -> list[Watch]:
        return list(self._watches)

    def live_status(self, url: str) -> str:
        return self._live.get(url, "")

    def has_enabled(self) -> bool:
        return any(w.enabled for w in self._watches)

    def is_running(self) -> bool:
        return self.runner.is_running()

    def problem(self) -> str:
        """Why scheduled checks can't run right now ('' if they can)."""
        return self._problem

    # ---- editing
    def follow(self, urls: list[str], folder: str | None, names: dict[str, str] | None = None) -> list[str]:
        """Follow links (already followed ones are left as they are). Returns the ones added."""
        self._watches, added = add_watches(self._watches, urls, folder)
        if names:
            self._watches = [w.with_changes(name=names[w.url]) if w.url in added and names.get(w.url) else w
                             for w in self._watches]
        if added:
            self._save()
            nameless = [w.url for w in self._watches if w.url in added and not w.name]
            if nameless:
                self.names_needed.emit(nameless)
            QTimer.singleShot(0, self.tick)
        return added

    def unfollow(self, urls: list[str]) -> None:
        gone = set(urls)
        self._watches = [w for w in self._watches if w.url not in gone]
        self._forced -= gone
        self._save()
        self._stop_if_running(gone)

    def update_watch(self, url: str, **changes) -> None:
        self.update_watches([url], **changes)

    def update_watches(self, urls: list[str], **changes) -> None:
        """Change several followed links at once (one save)."""
        targets = set(urls)
        self._watches = [w.with_changes(**changes) if w.url in targets else w for w in self._watches]
        self._save()
        if changes.get("enabled"):
            QTimer.singleShot(0, self.tick)
        elif changes.get("enabled") is False:
            self._forced -= targets
            self._stop_if_running(targets)

    def _stop_if_running(self, urls: set[str]) -> None:
        """Unfollowed or paused while being checked: stop now (the others are checked again next time)."""
        if self.runner.is_running() and any(u in urls and u not in self._run_done for u in self._run_urls):
            self.runner.stop()

    def set_name(self, url: str, name: str, kind: str = "") -> None:
        watch = self._find(url)
        if watch is None or not name:
            return
        changes = {}
        if not watch.name:
            changes["name"] = name
        if kind and kind != watch.kind:
            changes["kind"] = kind
        if changes:
            self.update_watch(url, **changes)

    # ---- running checks
    def check_now(self, urls: list[str] | None = None) -> None:
        """Check these links (default: every followed one) as soon as nothing else is downloading."""
        wanted = urls if urls is not None else [w.url for w in self._watches if w.enabled]
        for url in wanted:
            if self._find(url) is not None and url not in self._run_urls:
                self._forced.add(url)
                self._live[url] = WAITING
        self.changed.emit()
        self.tick()

    def pause(self) -> None:
        """Stop a running check; the playlists it didn't finish are checked again later."""
        if self.runner.is_running():
            self.runner.stop()

    def tick(self) -> None:
        if self.runner.is_running() or self._your_runner.is_running():
            return
        now = time.time()
        interval = self._state.settings.watch_interval_hours
        due = [w for w in self._watches if w.url in self._forced or is_due(w, now, interval)]
        if not due:
            self._set_problem("")
            return
        problem = self._cant_run()
        self._set_problem(problem)
        if problem:
            return
        self._run_urls = [w.url for w in due]
        self._run_done = set()
        for watch in due:
            self._live[watch.url] = WAITING
        self.log.emit("info", f"Checking {len(due)} followed playlist(s) for new tracks")
        self.runner.start([(row, w.as_job()) for row, w in enumerate(due)], self._state.settings)
        self.changed.emit()  # after starting, so the page shows "checking now"

    def _cant_run(self) -> str:
        settings = self._state.settings
        if not Path(settings.library).is_dir():
            return f"Waiting for the library folder ({settings.library}) - is the drive connected?"
        if not find_ffmpeg(settings):
            return "FFmpeg isn't installed (Setup & updates), so nothing can be converted to MP3."
        return ""

    def _set_problem(self, problem: str) -> None:
        if problem != self._problem:
            self._problem = problem
            if problem:
                self.log.emit("warn", f"Followed playlists: {problem}")
            self.changed.emit()

    # ---- runner events
    def _url(self, row: int) -> str:
        return self._run_urls[row] if 0 <= row < len(self._run_urls) else ""

    def _on_job_started(self, row: int) -> None:
        url = self._url(row)
        watch = self._find(url)
        name = (watch.name or url) if watch else url
        self.status.emit(f"Checking followed playlist {row + 1} of {len(self._run_urls)}: {name}")
        self._set_live(url, CHECKING)

    def _on_job_progress(self, row: int, item: int, total: int, _track: str) -> None:
        if total:
            self._set_live(self._url(row), f"Checking {item} of {total}...")

    def _set_live(self, url: str, text: str) -> None:
        if self._live.get(url) != text:  # progress repeats itself for every track: only real changes
            self._live[url] = text
            self.live_changed.emit(url)

    def _on_job_finished(self, row: int, status: str, counts: JobCounts) -> None:
        url = self._url(row)
        self._live.pop(url, None)
        self._run_done.add(url)
        if status == "Stopped":
            self.changed.emit()
            return
        self._forced.discard(url)
        watch = self._find(url)
        if watch is not None:
            now = time.time()
            self._watches = [record_check(w, now, status, counts) if w.url == url else w for w in self._watches]
            self._save()
            if counts.saved:
                self.new_tracks.emit(watch.name or url, counts.saved)

    def _on_run_finished(self, totals: JobCounts, stopped: bool) -> None:
        for url in self._run_urls:
            self._live.pop(url, None)
        for url in self._forced:  # requested during the run: still waiting for their turn
            self._live[url] = WAITING
        self._run_urls = []
        self.changed.emit()
        if stopped:
            self.status.emit("")
            return
        self.status.emit(
            f"Followed playlists checked: {totals.saved} new track(s)." if totals.saved
            else "Followed playlists checked: no new tracks."
        )
        QTimer.singleShot(0, self.tick)

    # ---- helpers
    def _find(self, url: str) -> Watch | None:
        return next((w for w in self._watches if w.url == url), None)

    def _save(self) -> None:
        try:
            save_watches(self._watches)
        except OSError as err:  # e.g. the file is briefly locked: keep going, the next change saves again
            logger.warning("Couldn't save followed playlists: %s", err)
        self.changed.emit()
