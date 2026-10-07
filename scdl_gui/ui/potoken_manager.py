"""Sets up and updates the automatic PO-token generator in the background."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal

from scdl_gui import potoken
from scdl_gui.engine import find_js_runtime
from scdl_gui.ui.state import AppState


class _Bridge(QObject):
    progress = Signal(str)
    done = Signal(bool, str, bool)  # ok, message, was_update_check
    checked = Signal()


class PotManager(QObject):
    progress = Signal(str)  # a step of the setup, for the status line
    finished = Signal(bool, str)  # ok, message

    def __init__(self, state: AppState, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._busy = False
        self._bridge = _Bridge()
        self._bridge.progress.connect(self.progress.emit)
        self._bridge.done.connect(self._on_done)
        self._bridge.checked.connect(lambda: self._state.update(last_pot_check=time.time()))

    def is_busy(self) -> bool:
        return self._busy

    @staticmethod
    def node() -> str | None:
        runtime = find_js_runtime()
        return runtime if runtime and runtime.lower().endswith("node.exe") else None

    def setup(self) -> None:
        """Install (or reinstall) the latest generator."""
        node = self.node()
        if self._busy:
            return
        if not node:
            self.finished.emit(False, "Node.js is needed first - install it in Helper programs above.")
            return
        self._start(node, update_check=False)

    def check_for_update(self) -> None:
        """Once a day: quietly move an existing install to a newer generator version."""
        settings = self._state.settings
        current = potoken.installed()
        node = self.node()
        due = time.time() - settings.last_pot_check >= potoken.CHECK_INTERVAL_SECONDS
        if current and node and settings.auto_po_token and due and not self._busy:
            self._start(node, update_check=True, current=current.version)

    def _start(self, node: str, update_check: bool, current: str = "") -> None:
        self._busy = True

        def work() -> None:
            try:
                version = potoken.latest_version()
                self._bridge.checked.emit()
                if update_check and not potoken.is_newer(version, current):
                    self._bridge.done.emit(True, "", True)
                    return
                potoken.install(version, node, self._bridge.progress.emit)
                self._bridge.done.emit(True, f"Automatic PO tokens {version} are ready.", update_check)
            except potoken.PotError as err:
                self._bridge.done.emit(False, str(err), update_check)

        threading.Thread(target=work, daemon=True).start()

    def remove(self) -> None:
        if not self._busy:
            potoken.remove()
            self.finished.emit(True, "Automatic PO tokens were removed.")

    def _on_done(self, ok: bool, message: str, update_check: bool) -> None:
        self._busy = False
        if update_check and ok and not message:
            return  # already up to date
        self.finished.emit(ok, message)
