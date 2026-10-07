"""Small reusable widgets: page scaffolding, cards, option lists, token chips, status pill."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from scdl_gui.templates import TOKENS
from scdl_gui.ui import theme


def label(text: str, object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for item in items:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)
    return layout


class Page(QWidget):
    """A page with a big title/subtitle; `body` is a vertical layout for content."""

    def __init__(self, title: str, subtitle: str, scroll: bool = True) -> None:
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("PageBody")
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(32, 26, 32, 26)
        self.body.setSpacing(16)
        self.body.addWidget(label(title, "PageTitle"))
        self.body.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        self.body.addSpacing(4)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(content)
            outer.addWidget(area)
        else:
            outer.addWidget(content)

    def finish(self) -> None:
        self.body.addStretch(1)


class Card(QFrame):
    def __init__(self, title: str, description: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 18)
        self.body.setSpacing(10)
        self.title = label(title, "CardTitle")
        self.body.addWidget(self.title)
        if description:
            self.body.addWidget(label(description, "Muted", wrap=True))


class OptionList(QWidget):
    """Radio buttons, each with an optional muted description underneath."""

    changed = Signal(object)  # key of the selected option

    def __init__(self, options: list[tuple[object, str, str]]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._keys: list[object] = []
        self._rows: dict[object, QHBoxLayout] = {}
        for key, title, description in options:
            radio = QRadioButton(title)
            self._group.addButton(radio, len(self._keys))
            self._keys.append(key)
            row = hbox(radio, None, spacing=12)
            self._rows[key] = row
            layout.addLayout(row)
            if description:
                hint = label(description, "Hint", wrap=True)
                hint.setContentsMargins(26, 0, 0, 2)
                layout.addWidget(hint)
        self._group.idClicked.connect(lambda i: self.changed.emit(self._keys[i]))

    def add_extra(self, key, widget: QWidget, stretch: int = 1) -> None:
        """Put a widget (e.g. a text box) right after an option's radio button."""
        row = self._rows[key]
        row.insertWidget(1, widget, stretch)

    def value(self):
        index = self._group.checkedId()
        return self._keys[index] if index >= 0 else None

    def set_value(self, key) -> None:
        if key in self._keys:
            self._group.button(self._keys.index(key)).setChecked(True)


class TokenBar(QWidget):
    """Clickable {token} chips for building templates."""

    token_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for token in TOKENS:
            chip = QPushButton(token.label)
            chip.setObjectName("Chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"{{{token.name}}} - {token.hint}")
            chip.clicked.connect(lambda _=False, name=token.name: self.token_clicked.emit(f"{{{name}}}"))
            layout.addWidget(chip)
        layout.addStretch(1)


class StatusPill(QLabel):
    _STYLES = {
        "ok": (theme.SUCCESS, "#E7F4EC"),
        "warn": (theme.WARNING, "#FBF0DF"),
        "error": (theme.DANGER, "#FBE7E4"),
        "busy": (theme.MUTED, "#EFEBE5"),
    }

    def set_state(self, level: str, text: str) -> None:
        fg, bg = self._STYLES.get(level, self._STYLES["busy"])
        self.setText(text)
        self.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:11px; padding:3px 10px; font-weight:600;")
