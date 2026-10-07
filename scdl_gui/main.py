"""Entry point. `--worker ...` runs the download worker (no Qt); anything else opens the app."""

from __future__ import annotations

import importlib.util
import logging
import platform
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

from scdl_gui import APP_ID, APP_NAME, APP_VERSION, GITHUB_URL

REQUIRED_MODULES = {"yt_dlp": "yt-dlp", "scdl": "scdl", "mutagen": "mutagen"}
LOCK_WAIT_MS = 4000  # an updated copy restarting waits for the old one to close
TEMP_MAX_AGE_SECONDS = 24 * 60 * 60


def _run_worker(args: list[str]) -> int:
    """Background worker: errors go to its output (read by the app), never to a pop-up."""
    try:
        from scdl_gui import worker

        return worker.main(args)
    except KeyboardInterrupt:
        return 130
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 1
    except BaseException:  # noqa: BLE001 - last line of defence for a headless process
        report = "ERROR: The download worker crashed:\n" + traceback.format_exc()
        stream = sys.stderr or sys.stdout
        if stream is not None:
            print(report, file=stream, flush=True)
        else:  # packaged app started without pipes: keep the details somewhere findable
            from scdl_gui.settings import data_dir

            with open(data_dir() / "worker-crash.log", "a", encoding="utf-8") as log:
                log.write(report + "\n")
        return 1


def _set_windows_app_id() -> None:
    """Own taskbar icon/grouping instead of Python's."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _setup_logging(folder) -> None:
    handler = RotatingFileHandler(folder / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.info("Starting %s %s on Python %s, %s", APP_NAME, APP_VERSION, platform.python_version(), platform.platform())


def _clean_temp_files(folder) -> None:
    cutoff = time.time() - TEMP_MAX_AGE_SECONDS
    for path in (folder / "tmp").glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _missing_modules() -> list[str]:
    return [package for module, package in REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]


def _run_app() -> int:
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from scdl_gui.settings import data_dir, load_settings, resource_path
    from scdl_gui.ui.main_window import MainWindow
    from scdl_gui.ui.state import AppState
    from scdl_gui.ui.theme import apply_theme

    folder = data_dir()
    _setup_logging(folder)
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(resource_path("assets", "icon.ico"))))
    apply_theme(app)

    lock = QLockFile(str(folder / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(LOCK_WAIT_MS):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already open.")
        return 0

    missing = _missing_modules()
    if missing:
        QMessageBox.critical(
            None, APP_NAME,
            "Some parts of the app are missing: " + ", ".join(missing) + ".\n\n"
            "If you run it from source, start it with run.bat (it installs everything), "
            f"or download the ready-made app from {GITHUB_URL}/releases.",
        )
        return 1

    def report_crash(kind, value, tb) -> None:
        details = "".join(traceback.format_exception(kind, value, tb))
        logging.error("Unhandled error:\n%s", details)
        QMessageBox.critical(
            None, APP_NAME,
            f"Something went wrong:\n\n{value}\n\nDetails were saved to app.log "
            "(Setup & updates > Open settings & logs folder). Please include it if you report the problem.",
        )

    sys.excepthook = report_crash
    _clean_temp_files(folder)
    window = MainWindow(AppState(load_settings()))
    window.show()
    try:
        return app.exec()
    finally:
        lock.unlock()


def main(args: list[str]) -> int:
    if args[:1] == ["--worker"]:
        return _run_worker(args[1:])
    return _run_app()


def run() -> None:
    """Console/GUI script entry point (pyproject)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    run()
