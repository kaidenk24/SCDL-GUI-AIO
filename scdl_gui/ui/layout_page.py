"""Save layout page: folder structure, file names, and how already-downloaded tracks are handled."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLineEdit, QVBoxLayout

from scdl_gui.templates import FILE_PRESETS, FOLDER_PRESETS, preview_paths, unknown_tokens
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, OptionList, Page, TokenBar, label

CUSTOM = "custom"
ARCHIVE_OPTIONS = [
    (
        "shared",
        "Download every track only once (recommended)",
        "Remembers everything you've downloaded. If a track is in two playlists it's saved in the "
        "first one only. Fastest, no duplicate files.",
    ),
    (
        "per_link",
        "Every folder gets all of its tracks",
        "Each link remembers its own downloads, so a track that's in several playlists is saved in "
        "each of their folders.",
    ),
    (
        "files",
        "Just check for existing files",
        "Skips a track only if a file with the same name is already in its folder.",
    ),
]


class TemplateChooser(Card):
    """Preset radio list + a custom template box."""

    def __init__(self, title: str, description: str, presets, on_change) -> None:
        super().__init__(title, description)
        self._presets = dict((template, name) for name, template in presets)
        self._on_change = on_change
        options = [(template, name, self._example(template)) for name, template in presets]
        options.append((CUSTOM, "Custom", "Build your own with the tokens below"))
        self.options = OptionList(options)
        self.options.changed.connect(self._preset_chosen)
        self.body.addWidget(self.options)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("e.g. {owner}\\{playlist}")
        self.custom.textEdited.connect(self._custom_edited)
        self.custom.setMaximumWidth(520)
        self.options.add_extra(CUSTOM, self.custom)
        self.warning = label("", "Warning")
        self.warning.hide()
        self.body.addWidget(self.warning)

    @staticmethod
    def _example(template: str) -> str:
        return f"Pattern: {template}" if template else "Files go straight into the library folder"

    def set_template(self, template: str) -> None:
        self.options.set_value(template if template in self._presets else CUSTOM)
        if self.custom.text() != template:
            self.custom.setText(template)
        self.custom.setEnabled(self.options.value() == CUSTOM)
        bad = unknown_tokens(template)
        self.warning.setVisible(bool(bad))
        self.warning.setText(f"Unknown token(s): {', '.join('{' + b + '}' for b in bad)} - they'll be used as plain text.")

    def insert_token(self, token: str) -> None:
        self.options.set_value(CUSTOM)
        self.custom.setEnabled(True)
        self.custom.insert(token)
        self._on_change(self.custom.text())

    def _preset_chosen(self, key) -> None:
        if key == CUSTOM:
            self.custom.setEnabled(True)
            self.custom.setFocus()
            self._on_change(self.custom.text())
        else:
            self._on_change(key)

    def _custom_edited(self, text: str) -> None:
        self.options.set_value(CUSTOM)
        self._on_change(text)


class LayoutPage(Page):
    def __init__(self, state: AppState) -> None:
        super().__init__(
            "Save layout",
            "Choose how folders and files are named. Links set to 'Auto' in the queue use this layout; "
            "links sent to one of your own folders use that folder instead.",
        )
        self._state = state
        self._last_focused: TemplateChooser | None = None

        self.folders = TemplateChooser(
            "Folder layout", "Folders created inside your library for each track.",
            FOLDER_PRESETS, lambda t: state.update(folder_template=t),
        )
        self.files = TemplateChooser(
            "File names", "What each MP3 is called (.mp3 is added for you).",
            [(name, t) for name, t in FILE_PRESETS], lambda t: state.update(file_template=t),
        )
        for chooser in (self.folders, self.files):
            chooser.custom.installEventFilter(self)
        self.body.addWidget(self.folders)
        self.body.addWidget(self.files)
        self.body.addWidget(self._build_tokens())
        self.body.addWidget(self._build_preview())

        archive = Card("Tracks you already have", "How the app knows a track was downloaded before.")
        self.archive = OptionList(ARCHIVE_OPTIONS)
        self.archive.changed.connect(lambda mode: state.update(archive_mode=mode))
        archive.body.addWidget(self.archive)
        self.body.addWidget(archive)
        self.finish()

        self._preview_timer = QTimer(self, singleShot=True, interval=150, timeout=self._update_preview)
        state.settings_changed.connect(lambda _s: self._load())
        self._load()

    def _build_tokens(self) -> Card:
        card = Card(
            "Tokens",
            "Click a token to add it to the custom folder layout or file name you're editing. "
            "Use \\ to make subfolders. Playlist-only tokens are left out for single-track links.",
        )
        tokens = TokenBar()
        tokens.token_clicked.connect(lambda t: (self._last_focused or self.files).insert_token(t))
        card.body.addWidget(tokens)
        return card

    def _build_preview(self) -> Card:
        card = Card("Preview", "Where files would be saved with these settings:")
        frame = QFrame()
        frame.setObjectName("Preview")
        self.preview_layout = QVBoxLayout(frame)
        self.preview_layout.setContentsMargins(14, 10, 14, 10)
        self.preview_layout.setSpacing(2)
        card.body.addWidget(frame)
        return card

    def eventFilter(self, watched, event) -> bool:
        if event.type() == event.Type.FocusIn:
            self._last_focused = self.folders if watched is self.folders.custom else self.files
        return False

    def _load(self) -> None:
        settings = self._state.settings
        self.folders.set_template(settings.folder_template)
        self.files.set_template(settings.file_template)
        self.archive.set_value(settings.archive_mode)
        self._preview_timer.start()

    def _update_preview(self) -> None:
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        settings = self._state.settings
        try:
            rows = preview_paths(settings.library, settings.folder_template, settings.file_template)
        except Exception as err:  # a half-typed template must never crash the page
            rows = [("Can't preview", str(err))]
        for caption, path in rows:
            self.preview_layout.addWidget(label(caption, "Hint"))
            self.preview_layout.addWidget(label(path, "Mono", wrap=True))
