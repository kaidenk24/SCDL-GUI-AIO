"""Background work for the UI: download worker processes, name lookups and the login check."""

from __future__ import annotations

import json
import subprocess
import uuid
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from scdl_gui.engine import worker_args, worker_command, worker_env
from scdl_gui.parsing import Event, JobCounts, OutputParser
from scdl_gui.settings import Job, Settings, data_dir

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WorkerProcess(QObject):
    """One worker process; emits its output line by line."""

    line = Signal(str)
    finished = Signal(int)  # exit code, -1 if it crashed or was killed

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._buffer = ""
        self._done = False

    def start(self, args: list[str], env: dict[str, str]) -> None:
        command = worker_command()
        environment = QProcessEnvironment.systemEnvironment()
        for key, value in env.items():
            environment.insert(key, value)
        self._process.setProcessEnvironment(environment)
        self._process.start(command[0], [*command[1:], *args])

    def is_running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def kill(self) -> None:
        """Stop the worker and everything it started (ffmpeg)."""
        pid = self._process.processId()
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        self._process.kill()

    def _read(self) -> None:
        self._buffer += bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        *lines, self._buffer = self._buffer.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for text in lines:
            if text.strip():
                self.line.emit(text)

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._read()
        if self._buffer.strip():
            self.line.emit(self._buffer)
        self._buffer = ""
        self._emit_finished(code if status == QProcess.ExitStatus.NormalExit else -1)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.line.emit(f"ERROR: Could not start the download worker ({self._process.program()}).")
            self._emit_finished(-1)

    def _emit_finished(self, code: int) -> None:
        if not self._done:
            self._done = True
            self.finished.emit(code)


class DownloadRunner(QObject):
    """Downloads queued links one after another."""

    job_started = Signal(int)  # queue row
    job_progress = Signal(int, int, int, str)  # row, item, total, current track
    job_finished = Signal(int, str, object)  # row, status text, JobCounts of that link
    job_named = Signal(int, str)  # row, playlist name seen while downloading
    drm_found = Signal(dict)  # a DRM-protected track to match on YouTube
    log = Signal(str, str)  # level (info/ok/skip/error/warn/detail), text
    totals_changed = Signal(object)  # JobCounts
    status = Signal(str)
    finished = Signal(object, bool)  # JobCounts, stopped

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: deque[tuple[int, Job]] = deque()
        self._settings: Settings | None = None
        self._process: WorkerProcess | None = None
        self._row = -1
        self._job_counts = JobCounts()
        self._totals = JobCounts()
        self._parser = OutputParser()
        self._stopping = False
        self._item = (0, 0)

    def is_running(self) -> bool:
        return self._process is not None

    def start(self, entries: list[tuple[int, Job]], settings: Settings) -> None:
        if self.is_running() or not entries:
            return
        self._pending = deque(entries)
        self._settings = settings
        self._totals = JobCounts()
        self._stopping = False
        self.totals_changed.emit(self._totals)
        self._run_next()

    def stop(self) -> None:
        if not self.is_running():
            return
        self._stopping = True
        self._pending.clear()
        self.status.emit("Stopping...")
        self._process.kill()

    def _run_next(self) -> None:
        if not self._pending:
            self._process = None
            self.finished.emit(self._totals, self._stopping)
            return
        self._row, job = self._pending.popleft()
        self._job_counts = JobCounts()
        self._parser = OutputParser()
        self._item = (0, 0)
        self.job_started.emit(self._row)
        self.log.emit("info", f"> {job.name or job.url}")
        self._process = WorkerProcess(self)
        self._process.line.connect(self._on_line)
        self._process.finished.connect(self._on_finished)
        try:
            args = worker_args(self._settings, job)
        except OSError as err:
            self.log.emit("error", f"  Can't use the destination folder: {err}")
            self._on_finished(-1)
            return
        self._process.start(args, worker_env(self._settings, job.url))

    def _on_line(self, text: str) -> None:
        self.log.emit("detail", text)
        event = self._parser.feed(text)
        if event is not None:
            self._handle(event)

    def _handle(self, event: Event) -> None:
        row = self._row
        if event.kind == "playlist":
            self.job_named.emit(row, event.text)
        elif event.kind == "item":
            self._item = (event.current, event.total)
            self.job_progress.emit(row, event.current, event.total, "")
        elif event.kind == "track":
            self.job_progress.emit(row, *self._item, event.text)
        elif event.kind == "saved":
            self._count("saved")
            self.log.emit("ok", f"  + {event.text}")
        elif event.kind == "skipped":
            self._count("skipped")
            self.log.emit("skip", f"  = already have: {event.text}")
        elif event.kind == "error":
            track = event.data.get("track", "")
            prefix = f"{track} - " if track else ""
            if event.data.get("drm") and self._settings.youtube_fallback:
                self.log.emit("warn", f"  ~ {prefix}DRM-protected on SoundCloud - looking for it on YouTube")
            else:
                self._count("failed")
                self.log.emit("error", f"  x {prefix}{event.text}")
        elif event.kind == "drm":
            self._count("to_match")
            self.drm_found.emit(event.data)
        elif event.kind == "rate":
            self.status.emit("Waiting for SoundCloud's rate limit...")
            self.log.emit("warn", f"  ! {event.text}")
        elif event.kind == "loudness":
            self.log.emit("detail", f"  volume {event.text}")

    def _count(self, field: str) -> None:
        setattr(self._job_counts, field, getattr(self._job_counts, field) + 1)
        setattr(self._totals, field, getattr(self._totals, field) + 1)
        self.totals_changed.emit(self._totals)

    def _on_finished(self, code: int) -> None:
        counts = self._job_counts
        if self._stopping:
            status = "Stopped"
        elif code != 0 and counts.saved == 0 and counts.skipped == 0 and counts.to_match == 0:
            status = "Failed" if counts.failed else "Failed - see Activity"
        else:
            status = f"Done - {counts.summary()}"
        self.job_finished.emit(self._row, status, counts)
        self.log.emit("info", f"  {status}")
        if self._process is not None:
            self._process.deleteLater()
        self._process = None
        self._run_next()


class LookupRunner(QObject):
    """Fetches playlist names/kinds for links in the background."""

    described = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._waiting: list[str] = []
        self._process: WorkerProcess | None = None
        self._settings: Settings | None = None
        self._parser = OutputParser()

    def lookup(self, urls: list[str], settings: Settings) -> None:
        self._settings = settings
        self._waiting.extend(u for u in urls if u not in self._waiting)
        if self._process is None:
            self._start()

    def _start(self) -> None:
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if not self._waiting:
            return
        urls, self._waiting = self._waiting, []
        self._process = WorkerProcess(self)
        self._process.line.connect(self._on_line)
        self._process.finished.connect(lambda _code: self._start())
        self._process.start(["--describe", *urls], worker_env(self._settings))

    def _on_line(self, text: str) -> None:
        event = self._parser.feed(text)
        if event is not None and event.kind == "describe":
            self.described.emit(event.data)


class LoginChecker(QObject):
    """Checks Firefox for SoundCloud and YouTube logins. States: 'yes', 'no', 'off' or 'error'."""

    checked = Signal(str, str)  # SoundCloud state, detail
    youtube_checked = Signal(str)  # YouTube state

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: WorkerProcess | None = None
        self._lines: list[str] = []
        self._settings: Settings | None = None

    def check(self, settings: Settings) -> None:
        self._settings = settings
        if not settings.use_login and not settings.youtube_login:
            self.checked.emit("off", "")
            self.youtube_checked.emit("off")
            return
        if self._process is not None:
            return
        self._lines = []
        self._process = WorkerProcess(self)
        self._process.line.connect(self._lines.append)
        self._process.finished.connect(self._on_finished)
        self._process.start(["--check-cookies"], worker_env(settings))

    def _on_finished(self, code: int) -> None:
        if self._process is not None:
            self._process.deleteLater()
        self._process = None
        parser = OutputParser()
        result = next((e.data for e in map(parser.feed, self._lines) if e is not None and e.kind == "login"), None)
        if code != 0 or result is None:
            detail = self._lines[-1].strip() if self._lines else "Firefox cookies could not be read"
            self.checked.emit("error", detail)
            self.youtube_checked.emit("error")
            return

        def state(enabled: bool, logged_in: bool) -> str:
            return "off" if not enabled else "yes" if logged_in else "no"

        self.checked.emit(state(self._settings.use_login, result.get("soundcloud", False)), "")
        self.youtube_checked.emit(state(self._settings.youtube_login, result.get("youtube", False)))


def _job_file(name: str, payload) -> str:
    folder = data_dir() / "tmp"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


class MatchSearchRunner(QObject):
    """Searches YouTube for DRM-protected tracks, a batch at a time."""

    found = Signal(dict)  # {"key", "query", "candidates", "error"?}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._waiting: list[dict] = []
        self._process: WorkerProcess | None = None
        self._file = ""
        self._settings: Settings | None = None

    def search(self, items: list[dict], settings: Settings) -> None:
        """items: {"key", "track", "query"?}"""
        self._settings = settings
        queued = {i["key"] for i in self._waiting}
        self._waiting.extend(i for i in items if i["key"] not in queued)
        if self._process is None:
            self._start()

    def _start(self) -> None:
        self._cleanup()
        if not self._waiting:
            return
        batch, self._waiting = self._waiting, []
        self._file = _job_file("search", batch)
        parser = OutputParser()
        self._process = WorkerProcess(self)
        self._process.line.connect(lambda text: self._on_line(parser, text))
        self._process.finished.connect(lambda _code: self._start())
        self._process.start(["--yt-search", self._file], worker_env(self._settings))

    def _on_line(self, parser: OutputParser, text: str) -> None:
        event = parser.feed(text)
        if event is not None and event.kind == "ytmatch":
            self.found.emit(event.data)

    def _cleanup(self) -> None:
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if self._file:
            Path(self._file).unlink(missing_ok=True)
            self._file = ""


class MatchDownloadRunner(QObject):
    """Downloads confirmed YouTube matches one at a time."""

    done = Signal(str, bool, str)  # key, ok, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: deque[tuple[dict, Settings]] = deque()
        self._process: WorkerProcess | None = None
        self._job: dict | None = None
        self._result: dict | None = None
        self._file = ""

    def download(self, job: dict, settings: Settings) -> None:
        """job: {"key", "url", "target", "track", "archive"}"""
        self._pending.append((job, settings))
        if self._process is None:
            self._start()

    def _start(self) -> None:
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if self._file:
            Path(self._file).unlink(missing_ok=True)
            self._file = ""
        if not self._pending:
            return
        self._job, settings = self._pending.popleft()
        self._result = None
        self._file = _job_file("download", self._job)
        parser = OutputParser()
        self._process = WorkerProcess(self)
        self._process.line.connect(lambda text: self._on_line(parser, text))
        self._process.finished.connect(self._on_finished)
        self._process.start(["--yt-download", self._file], worker_env(settings))

    def _on_line(self, parser: OutputParser, text: str) -> None:
        event = parser.feed(text)
        if event is not None and event.kind == "ytdone":
            self._result = event.data

    def _on_finished(self, _code: int) -> None:
        result = self._result or {"ok": False, "message": "The download worker stopped unexpectedly"}
        self.done.emit(self._job["key"], bool(result.get("ok")), result.get("message", ""))
        self._start()
