"""Apple-inspired Qt style sheet for the desktop grading UI.

The palette follows apple.com: a neutral canvas, generous spacing, pill-shaped
controls and the system blue accent. The dark theme mirrors the apple.com dark
surfaces instead of tinting the light palette, so both themes stay legible.

Only two entry points are public:

* :func:`get_app_style` returns the full style sheet for ``"light"``/``"dark"``.
* :data:`SPELL_HINT_COLOR` is the wave-underline colour for spelling hints,
  chosen to stay readable on both themes.
"""

from __future__ import annotations

from typing import Any

SPELL_HINT_COLOR = "#ff3b30"

FONT_STACK = '"Microsoft YaHei", "Segoe UI", "Arial"'


def prepare_fonts(application) -> None:
    """Load system fonts if a headless Windows Qt backend enumerates none."""
    import os
    from pathlib import Path
    from PyQt6.QtGui import QFont, QFontDatabase
    if os.name == "nt" and not QFontDatabase.families():
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            path = font_dir / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    application.setFont(QFont("Microsoft YaHei" if os.name == "nt" else "Sans Serif", 10))

LIGHT: dict[str, str] = {
    "canvas": "#ffffff",
    "surface": "#f5f5f7",
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "line": "#d2d2d7",
    "accent": "#0071e3",
    "accent_hover": "#0077ed",
    "accent_press": "#006edb",
    "accent_soft": "rgba(0, 113, 227, 0.12)",
    "hover": "rgba(0, 0, 0, 0.05)",
    "selection": "rgba(0, 113, 227, 0.18)",
    "danger": "#e30000",
    "danger_soft": "rgba(227, 0, 0, 0.08)",
    "success": "#00a05a",
    "field": "#ffffff",
    "grid": "#e8e8ed",
    "scroll": "#c7c7cc",
    "scroll_hover": "#a1a1a6",
    "disabled_text": "#a1a1a6",
    "disabled_bg": "#f5f5f7",
    "tooltip_bg": "#ffffff",
    "hero_bg": "#f5f7fb",
    "hero_text": "#17243b",
    "hero_muted": "#86868b",
    "hero_line": "rgba(255, 255, 255, 0.28)",
    "hero_hover": "rgba(255, 255, 255, 0.12)",
}

DARK: dict[str, str] = {
    "canvas": "#000000",
    "surface": "#1d1d1f",
    "text": "#f5f5f7",
    "muted": "#86868b",
    "line": "#424245",
    "accent": "#2997ff",
    "accent_hover": "#51a9ff",
    "accent_press": "#1f8bff",
    "accent_soft": "rgba(41, 151, 255, 0.18)",
    "hover": "rgba(255, 255, 255, 0.07)",
    "selection": "rgba(41, 151, 255, 0.30)",
    "danger": "#ff453a",
    "danger_soft": "rgba(255, 69, 58, 0.14)",
    "success": "#30d158",
    "field": "#1d1d1f",
    "grid": "#2c2c2e",
    "scroll": "#48484a",
    "scroll_hover": "#636366",
    "disabled_text": "#6e6e73",
    "disabled_bg": "#1d1d1f",
    "tooltip_bg": "#1d1d1f",
    "hero_bg": "#1d1d1f",
    "hero_text": "#f5f5f7",
    "hero_muted": "#a1a1a6",
    "hero_line": "rgba(255, 255, 255, 0.24)",
    "hero_hover": "rgba(255, 255, 255, 0.10)",
}

_TEMPLATE = """
/* ---------------------------------------------------------------- base --- */
QWidget {
    font-family: %(font)s;
    font-size: 14px;
    color: %(text)s;
}

QMainWindow, QWidget#root, QStackedWidget {
    background: %(canvas)s;
}

QScrollArea {
    background: transparent;
    border: 0;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QFrame#sidebar {
    background: %(surface)s;
    border: 0;
    border-right: 1px solid %(line)s;
}

/* --------------------------------------------------------------- type ---- */
QLabel {
    background: transparent;
}

QLabel[title="true"] {
    font-size: 30px;
    font-weight: 600;
    color: %(text)s;
}

QLabel[subtitle="true"] {
    font-size: 15px;
    color: %(muted)s;
}

QLabel[section="true"] {
    font-size: 16px;
    font-weight: 600;
    color: %(text)s;
}

QLabel[cardTitle="true"] {
    font-size: 17px;
    font-weight: 600;
    color: %(text)s;
}

QLabel[fieldLabel="true"] {
    font-size: 13px;
    font-weight: 600;
    color: %(muted)s;
}

QLabel[metricLabel="true"] {
    font-size: 13px;
    color: %(muted)s;
}

QLabel[metricValue="true"] {
    font-size: 24px;
    font-weight: 600;
    color: %(accent)s;
}

QLabel[score="true"] {
    font-size: 44px;
    font-weight: 600;
    color: %(accent)s;
}

QLabel[tag="true"] {
    background: %(accent_soft)s;
    color: %(accent)s;
    border: 0;
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 13px;
    font-weight: 600;
}

QFrame#sidebar QLabel#brand {
    font-size: 16px;
    font-weight: 600;
    color: %(text)s;
}

/* --------------------------------------------------------------- cards --- */
QFrame[card="true"] {
    background: %(surface)s;
    border: 1px solid transparent;
    border-radius: 18px;
}

QFrame[card="true"]:hover {
    background: %(grid)s;
}

QFrame[tile="true"] {
    background: %(surface)s;
    border: 1px solid transparent;
    border-radius: 14px;
}

QFrame[tile="true"]:hover {
    background: %(grid)s;
}

/* ---------------------------------------------------------------- hero --- */
QFrame[hero="true"] {
    background: %(hero_bg)s;
    border: 0;
}

QFrame[hero="true"] QLabel[title="true"] {
    font-size: 44px;
    font-weight: 600;
    color: %(hero_text)s;
}

QFrame[hero="true"] QLabel[subtitle="true"] {
    font-size: 19px;
    color: %(hero_muted)s;
}

QFrame[hero="true"] QLabel[eyebrow="true"] {
    color: %(accent)s;
}

/* ------------------------------------------------------------ chapters --- */
QLabel[eyebrow="true"] {
    font-size: 13px;
    font-weight: 600;
    color: %(accent)s;
}

QLabel[chapterTitle="true"] {
    font-size: 30px;
    font-weight: 600;
    color: %(text)s;
}

QLabel[body="true"] {
    font-size: 15px;
    color: %(muted)s;
}

QLabel[statValue="true"] {
    font-size: 34px;
    font-weight: 600;
    color: %(text)s;
}

QLabel[statCaption="true"] {
    font-size: 13px;
    color: %(muted)s;
}

/* --------------------------------------------------------------- links --- */
QPushButton[link="true"] {
    background: transparent;
    border: 0;
    border-radius: 8px;
    padding: 4px 0;
    color: %(accent)s;
    font-size: 15px;
    text-align: left;
}

QPushButton[link="true"]:hover {
    background: transparent;
    color: %(accent_hover)s;
}

QFrame[hero="true"] QPushButton[link="true"] {
    color: %(accent)s;
}

QPushButton[onDark="true"] {
    background: transparent;
    color: %(hero_text)s;
    border: 1px solid %(hero_line)s;
    border-radius: 18px;
}

QPushButton[onDark="true"]:hover {
    background: %(hero_hover)s;
    border-color: %(hero_line)s;
}

/* ------------------------------------------------------------- buttons --- */
/*
 * Qt ignores border-radius values larger than half the widget height, so the
 * radii below stay inside that limit for every button height in this app.
 */
QPushButton {
    background: %(field)s;
    color: %(text)s;
    border: 1px solid %(line)s;
    border-radius: 18px;
    padding: 9px 20px;
    min-height: 20px;
    font-size: 14px;
}

QPushButton:hover {
    background: %(hover)s;
    border-color: %(line)s;
}

QPushButton:pressed {
    background: %(accent_soft)s;
}

QPushButton:disabled {
    background: %(disabled_bg)s;
    color: %(disabled_text)s;
    border-color: %(line)s;
}

QPushButton[primary="true"] {
    background: %(accent)s;
    color: #ffffff;
    border: 1px solid %(accent)s;
    border-radius: 18px;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background: %(accent_hover)s;
    border-color: %(accent_hover)s;
}

QPushButton[primary="true"]:pressed {
    background: %(accent_press)s;
    border-color: %(accent_press)s;
}

QPushButton[primary="true"]:disabled {
    background: %(disabled_bg)s;
    color: %(disabled_text)s;
    border-color: %(line)s;
}

QPushButton[danger="true"] {
    background: %(field)s;
    color: %(danger)s;
    border: 1px solid %(line)s;
    border-radius: 18px;
}

QPushButton[danger="true"]:hover {
    background: %(danger_soft)s;
    border-color: %(danger_soft)s;
}

QPushButton[success="true"] {
    background: %(success)s;
    color: #ffffff;
    border: 1px solid %(success)s;
    border-radius: 18px;
    font-weight: 600;
}

/* Small in-table row actions: lower radius and padding so the pill stays
 * round inside the short table rows. Declared last so it also rounds the
 * compact danger button. */
QPushButton[compact="true"] {
    padding: 5px 14px;
    min-height: 16px;
    border-radius: 10px;
    font-size: 13px;
}

QPushButton[nav="true"] {
    text-align: left;
    padding: 10px 16px;
    border: 0;
    border-radius: 12px;
    background: transparent;
    color: %(muted)s;
    font-size: 15px;
    min-height: 18px;
}

QPushButton[nav="true"]:hover {
    background: %(hover)s;
    color: %(text)s;
}

QPushButton[nav="true"]:checked {
    background: %(accent_soft)s;
    color: %(accent)s;
    font-weight: 600;
}

/* -------------------------------------------------------------- inputs --- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background: %(field)s;
    color: %(text)s;
    border: 1px solid %(line)s;
    border-radius: 12px;
    padding: 9px 12px;
    selection-background-color: %(selection)s;
    selection-color: %(text)s;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus {
    border: 1px solid %(accent)s;
}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled {
    background: %(disabled_bg)s;
    color: %(disabled_text)s;
}

/* Only the width is set here: styling the drop-down's border or background
 * (or adding a ::down-arrow rule) makes Qt drop the native arrow entirely. */
QComboBox::drop-down {
    width: 28px;
}

QComboBox QAbstractItemView {
    background: %(field)s;
    color: %(text)s;
    border: 1px solid %(line)s;
    border-radius: 12px;
    padding: 6px;
    outline: 0;
    selection-background-color: %(accent_soft)s;
    selection-color: %(accent)s;
}

/* -------------------------------------------------------------- tables --- */
QTableWidget, QTableView {
    background: %(field)s;
    alternate-background-color: %(field)s;
    border: 1px solid %(line)s;
    border-radius: 14px;
    gridline-color: %(grid)s;
    selection-background-color: %(selection)s;
    selection-color: %(text)s;
    outline: 0;
}

QTableWidget::item, QTableView::item {
    padding: 10px 8px;
    border: 0;
}

QHeaderView {
    background: transparent;
    border: 0;
}

QHeaderView::section {
    background: transparent;
    color: %(muted)s;
    border: 0;
    border-bottom: 1px solid %(line)s;
    padding: 10px 8px;
    font-weight: 600;
}

QTableCornerButton::section {
    background: transparent;
    border: 0;
}

/* ------------------------------------------------------------ controls --- */
QRadioButton {
    color: %(text)s;
    spacing: 10px;
    padding: 4px 0;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid %(line)s;
    background: %(field)s;
}

QRadioButton::indicator:hover {
    border-color: %(accent)s;
}

QRadioButton::indicator:checked {
    border: 5px solid %(accent)s;
    background: %(field)s;
}

QCheckBox {
    color: %(text)s;
    spacing: 10px;
    padding: 2px 0;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid %(line)s;
    background: %(field)s;
}

QCheckBox::indicator:hover {
    border-color: %(accent)s;
}

QCheckBox::indicator:checked {
    background: %(accent)s;
    border-color: %(accent)s;
}

QProgressBar {
    background: %(grid)s;
    border: 0;
    border-radius: 6px;
    text-align: center;
    color: %(muted)s;
    min-height: 12px;
}

QProgressBar::chunk {
    background: %(accent)s;
    border-radius: 6px;
}

QSplitter::handle {
    background: %(line)s;
}

QSplitter::handle:horizontal {
    width: 1px;
}

QSplitter::handle:vertical {
    height: 1px;
}

QSplitter::handle:hover {
    background: %(accent)s;
}

/* ------------------------------------------------------------ scrollbars - */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background: %(scroll)s;
    border-radius: 4px;
    min-height: 40px;
}

QScrollBar::handle:vertical:hover {
    background: %(scroll_hover)s;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}

QScrollBar::handle:horizontal {
    background: %(scroll)s;
    border-radius: 4px;
    min-width: 40px;
}

QScrollBar::handle:horizontal:hover {
    background: %(scroll_hover)s;
}

QScrollBar::add-line, QScrollBar::sub-line {
    background: transparent;
    border: 0;
    width: 0;
    height: 0;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ------------------------------------------------- dialogs and tooltips --- */
QDialog, QMessageBox, QInputDialog {
    background: %(canvas)s;
}

QMessageBox QLabel, QInputDialog QLabel {
    color: %(text)s;
}

QToolTip {
    background: %(tooltip_bg)s;
    color: %(text)s;
    border: 1px solid %(line)s;
    border-radius: 8px;
    padding: 6px 10px;
}
"""


def _render(palette: dict[str, str]) -> str:
    tokens: dict[str, Any] = dict(palette)
    tokens["font"] = FONT_STACK
    return _TEMPLATE % tokens


LIGHT_STYLE = _render(LIGHT)
DARK_STYLE = _render(DARK)


def get_app_style(theme: str) -> str:
    """Return the full application style sheet for the selected theme."""
    if str(theme).strip().lower() == "dark":
        return DARK_STYLE
    return LIGHT_STYLE
