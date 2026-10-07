"""'Install it for me' buttons for FFmpeg and Node.js, using Windows' built-in winget."""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from scdl_gui.system import Tool, has_winget, winget_install_args


class ToolInstaller(QObject):
    finished = Signal(str, bool)  # tool name, success

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._process: QProcess | None = None
        self._tool: Tool | None = None

    def is_busy(self) -> bool:
        return self._process is not None

    def install(self, tool: Tool) -> None:
        if self._process is not None:
            return
        if not has_winget():
            QMessageBox.information(
                self._parent, f"Install {tool.name}",
                f"Automatic install needs winget (App Installer from the Microsoft Store).\n"
                f"The {tool.name} download page will open instead.",
            )
            QDesktopServices.openUrl(QUrl(tool.download_page))
            return
        answer = QMessageBox.question(
            self._parent, f"Install {tool.name}",
            f"Install {tool.name} with winget (Windows' package manager)?\n\n"
            "This accepts the package's license. Windows may ask for permission.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._tool = tool
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start("winget", winget_install_args(tool))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._done(False, "winget couldn't be started.")

    def _on_finished(self, code: int, _status) -> None:
        output = bytes(self._process.readAll()).decode("utf-8", errors="replace") if self._process else ""
        # winget exit code 0x8A15002B: already installed / no newer version
        ok = code == 0 or "already installed" in output.lower() or code == -1978335189
        tail = "\n".join(line for line in output.splitlines() if line.strip())[-500:]
        self._done(ok, tail)

    def _done(self, ok: bool, detail: str) -> None:
        tool = self._tool
        if self._process is not None:
            self._process.deleteLater()
        self._process = None
        if tool is None:
            return
        if ok:
            QMessageBox.information(self._parent, f"Install {tool.name}", f"{tool.name} is installed.")
        else:
            QMessageBox.warning(self._parent, f"Install {tool.name}", f"{tool.name} couldn't be installed.\n\n{detail}")
        self.finished.emit(tool.name, ok)
