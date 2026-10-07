"""Colours and the Qt stylesheet. Warm neutral surfaces, SoundCloud orange as the one accent."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#FF5500"
ACCENT_HOVER = "#E64C00"
ACCENT_SOFT = "#FFF1E9"
ACCENT_LINE = "#FFD3BD"
BG = "#F5F3EF"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#FAF9F6"
BORDER = "#E4DFD7"
BORDER_STRONG = "#CDC5BA"
TEXT = "#1D1A17"
MUTED = "#6F685F"
SIDEBAR = "#1C1916"
SIDEBAR_ITEM = "#2C2723"
SIDEBAR_TEXT = "#CBC3B9"
SUCCESS = "#23824F"
WARNING = "#A86A12"
DANGER = "#C23A2A"

LEVEL_COLORS = {"ok": SUCCESS, "skip": MUTED, "error": DANGER, "warn": WARNING, "info": TEXT, "detail": "#9A9289"}

STYLESHEET = f"""
QWidget {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#Page, QWidget#PageBody, QScrollArea, QScrollArea > QWidget > QWidget#PageBody {{ background: {BG}; }}
QScrollArea {{ border: none; }}

QWidget#Sidebar {{ background: {SIDEBAR}; }}
QLabel#AppTitle {{ color: #FFFFFF; font-size: 12.5pt; font-weight: 600; }}
QLabel#AppVersion {{ color: #7D746A; font-size: 8.5pt; }}
QListWidget#Nav {{ background: transparent; border: none; color: {SIDEBAR_TEXT}; font-size: 10.5pt; outline: 0; }}
QListWidget#Nav::item {{ padding: 9px 12px; margin: 1px 10px; border-radius: 7px; }}
QListWidget#Nav::item:selected {{ background: {SIDEBAR_ITEM}; color: #FFFFFF; border-left: 3px solid {ACCENT}; }}
QListWidget#Nav::item:hover:!selected {{ background: #25211D; color: #FFFFFF; }}

QLabel#PageTitle {{ font-size: 19pt; font-weight: 600; }}
QLabel#PageSubtitle, QLabel#Muted {{ color: {MUTED}; }}
QLabel#Hint {{ color: {MUTED}; font-size: 9pt; }}
QLabel#CardTitle {{ font-size: 11.5pt; font-weight: 600; }}
QLabel#Mono {{ font-family: "Cascadia Mono", "Consolas"; font-size: 9.5pt; }}
QLabel#Warning {{ color: {WARNING}; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#Preview {{ background: {SURFACE_ALT}; border: 1px dashed {BORDER_STRONG}; border-radius: 8px; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {BORDER_STRONG}; background: {SURFACE_ALT}; }}
QPushButton:pressed {{ background: #EFEBE5; }}
QPushButton:disabled {{ color: #ABA399; background: {SURFACE_ALT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #FFFFFF; border: none; font-weight: 600; padding: 9px 22px; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: #F4BFA3; color: #FFFFFF; }}
QPushButton#Stop {{ color: {DANGER}; font-weight: 600; padding: 9px 18px; }}
QPushButton#Chip {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT_LINE}; color: #96390B; border-radius: 11px; padding: 3px 10px; font-size: 9pt; }}
QPushButton#Chip:hover {{ background: #FFE3D3; }}
QPushButton#Preset {{ border-radius: 13px; padding: 4px 12px; }}
QPushButton#Preset:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: #96390B; }}

QLineEdit, QPlainTextEdit, QComboBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ background: {SURFACE_ALT}; color: #ABA399; }}
QComboBox::drop-down {{ border: none; width: 22px; }}

QTableView, QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; alternate-background-color: {SURFACE_ALT}; outline: 0; }}
QTableView::item, QTreeWidget::item {{ padding: 6px 6px; }}
QTreeWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QHeaderView::section {{ background: {SURFACE_ALT}; border: none; border-bottom: 1px solid {BORDER}; padding: 7px 8px;
    font-weight: 600; color: {MUTED}; }}
QListWidget#Folders {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; outline: 0; }}
QListWidget#Folders::item {{ padding: 7px 8px; border-radius: 6px; margin: 1px 3px; }}
QListWidget#Folders::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget#Folders::item:hover:!selected {{ background: {SURFACE_ALT}; }}

QWidget#BottomBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QProgressBar {{ border: none; background: #ECE7E0; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {SURFACE}; border: 2px solid {ACCENT}; width: 14px; height: 14px; margin: -7px 0; border-radius: 9px; }}
QSlider::handle:horizontal:disabled {{ border-color: {BORDER_STRONG}; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDER_STRONG}; }}

QRadioButton, QCheckBox {{ spacing: 8px; padding: 2px 0; }}
QToolTip {{ background: {SIDEBAR}; color: #FFFFFF; border: none; padding: 6px 8px; border-radius: 4px; }}
QSplitter::handle {{ background: transparent; width: 10px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#A39B91"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
