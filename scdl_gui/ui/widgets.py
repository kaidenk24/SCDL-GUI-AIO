"""Small reusable widgets: page scaffolding, cards, option lists, token chips, status pill."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
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
    """A page with a big title/subtitle; `body` is a vertical layout for content.

    The content always sits in a scroll area: it fills the page when there's room (tables stretch) and
    scrolls instead of squashing when the window is small. Margins shrink on narrow windows, and settings
    pages (those that call finish()) stop growing wider than FORM_MAX_WIDTH on big screens."""

    WIDE_MARGINS = (32, 26)
    NARROW_MARGINS = (18, 16)
    NARROW_BELOW = 760  # page width in pixels
    FORM_MAX_WIDTH = 1100

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("PageBody")
        self.body = QVBoxLayout(content)
        self.body.setSpacing(16)
        self.body.addWidget(label(title, "PageTitle"))
        self.body.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        self.body.addSpacing(4)
        self._max_width: int | None = None
        self._margins: tuple[int, ...] = ()
        self._apply_margins(self.width())
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(content)
        outer.addWidget(area)

    def _apply_margins(self, width: int) -> None:
        narrow = width < self.NARROW_BELOW
        side, top = self.NARROW_MARGINS if narrow else self.WIDE_MARGINS
        right = side
        if self._max_width and width - 2 * side > self._max_width:
            right = width - side - self._max_width
        margins = (side, top, right, top)
        if margins != self._margins:
            self._margins = margins
            self.body.setContentsMargins(*margins)
            self.body.setSpacing(12 if narrow else 16)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_margins(event.size().width())

    def finish(self) -> None:
        self.body.addStretch(1)
        self._max_width = self.FORM_MAX_WIDTH
        self._apply_margins(self.width())


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


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto the next line when there isn't room."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        """Everything on one line."""
        shown = [item.sizeHint() for item in self._items if not item.isEmpty()]
        if not shown:
            return QSize()
        width = sum(s.width() for s in shown) + self._spacing * (len(shown) - 1)
        return QSize(width, max(s.height() for s in shown))

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, move: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height:
                x, y, line_height = rect.x(), y + line_height + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class FlowRow(QWidget):
    """A row of buttons that wraps onto a second line on narrow windows."""

    def __init__(self, *widgets: QWidget, spacing: int = 8) -> None:
        super().__init__()
        layout = FlowLayout(self, spacing)
        for widget in widgets:
            layout.addWidget(widget)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)


class ResponsiveSplitter(QSplitter):
    """Two panes side by side on wide pages, stacked (first on top) when narrower than `stack_below`."""

    def __init__(self, first: QWidget, second: QWidget, stack_below: int,
                 wide_sizes: tuple[int, int], stacked_sizes: tuple[int, int]) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(14)
        self.addWidget(first)
        self.addWidget(second)
        self._stack_below = stack_below
        self._sizes = {Qt.Orientation.Horizontal: list(wide_sizes), Qt.Orientation.Vertical: list(stacked_sizes)}
        self.setSizes(self._sizes[Qt.Orientation.Horizontal])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        wanted = Qt.Orientation.Vertical if event.size().width() < self._stack_below else Qt.Orientation.Horizontal
        if wanted != self.orientation():
            self.setOrientation(wanted)
            self.setSizes(self._sizes[wanted])


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with '...' to fit, instead of being cut off."""

    def __init__(self, text: str = "", object_name: str = "", mode=Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__()
        if object_name:
            self.setObjectName(object_name)
        self._full = text
        self._mode = mode
        self._elide()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 4)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(self.sizeHint().width(), 80))
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, max(self.width() - 2, 10)))


class TokenBar(QWidget):
    """Clickable {token} chips for building templates."""

    token_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = FlowLayout(self, spacing=6)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        for token in TOKENS:
            chip = QPushButton(token.label)
            chip.setObjectName("Chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"{{{token.name}}} - {token.hint}")
            chip.clicked.connect(lambda _=False, name=token.name: self.token_clicked.emit(f"{{{name}}}"))
            layout.addWidget(chip)


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
