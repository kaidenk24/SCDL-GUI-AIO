"""Shared, observable settings for all pages. Settings are immutable; update() swaps in a copy."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from scdl_gui.settings import Settings


class AppState(QObject):
    settings_changed = Signal(object)  # Settings

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings

    def update(self, **changes) -> None:
        updated = self._settings.with_changes(**changes)
        if updated != self._settings:
            self._settings = updated
            self.settings_changed.emit(updated)

    def replace(self, settings: Settings) -> None:
        self._settings = settings
        self.settings_changed.emit(settings)
