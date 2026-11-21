"""Editorial-inspired Qt style sheet for the desktop grading UI.

Warm paper, ink and an olive accent echo the local companion artwork.
The Unslop design guide (github.com/heydamir/unslop) informed the hierarchy:
let the work lead, use space rather than outlines, and distinguish keyboard
focus from the selected value in both light and dark themes.

Only two entry points are public:

* :func:`get_app_style` returns the full style sheet for ``"light"``/``"dark"``.
* :data:`SPELL_HINT_COLOR` is the wave-underline colour for spelling hints,
  chosen to stay readable on both themes.
"""

from __future__ import annotations

from typing import Any

from gui.local_assets import configured_asset_dir

SPELL_HINT_COLOR = "#b83f36"

FONT_STACK = '"Microsoft YaHei", "Segoe UI", "Arial"'


PRIVATE_FONT_FAMILY = "ResourceHanRounded CN"
# CRC/file names alone cannot authorize a locally supplied font.
# Only these two user-selected immutable font files may enter this app's font database.
PRIVATE_FONT_FILES = (
    ("ui-regular.ttf", "a1d07c36573da46d64da1a79ed246ee295089b75f19490adca5595847a98ee9a"),
    ("ui-bold.ttf", "2ea722d1e656b8a0cc9faa5118e41f37168527e9e3b226f79550ec4d0a587435"),
)
FONT_GLYPH_PROBE = "欢迎你奶家人写作历史设置批改，。！？CET-46WritingGrader123%"

def _private_font_dir():
    from pathlib import Path
    return configured_asset_dir("fonts") or Path(__file__).resolve().parents[1] / "work" / "preview" / "fonts"


def _load_private_family(application, directory):
    """Register the verified family for this Qt process only; never install system fonts."""
    import hashlib
    from pathlib import Path
    from PyQt6.QtGui import QFontDatabase, QRawFont
    root = Path(directory).resolve()
    cache = getattr(application, "_cet_local_font_families", None)
    if cache is None:
        cache = application._cet_local_font_families = {}
    added = []
    try:
        paths = [root / name for name, _ in PRIVATE_FONT_FILES]
        stamps = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
        key = (root, stamps)
        if key in cache:
            return cache[key]
        for path, (_, expected) in zip(paths, PRIVATE_FONT_FILES):
            if path.resolve().parent != root or not 0 < path.stat().st_size <= 32*1024*1024:
                raise ValueError("Invalid local font path or size")
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != expected:
                raise ValueError("Not the approved local font")
            raw = QRawFont(blob, 16.)
            if not raw.isValid() or not all(raw.supportsCharacter(ord(c)) for c in FONT_GLYPH_PROBE):
                raise ValueError("Cannot render the required bilingual interface")
            font_id = QFontDatabase.addApplicationFontFromData(blob)
            if font_id < 0:
                raise ValueError("Qt could not register the local face")
            added.append(font_id)
            if PRIVATE_FONT_FAMILY not in QFontDatabase.applicationFontFamilies(font_id):
                raise ValueError("Unexpected family registered by Qt")
        cache[key] = PRIVATE_FONT_FAMILY
        return PRIVATE_FONT_FAMILY
    except (OSError, ValueError, RuntimeError):
        for font_id in reversed(added):
            QFontDatabase.removeApplicationFont(font_id)
        return ""


def ui_font_stack(fallback=FONT_STACK):
    """QSS font stack; the application field is only ever a verified constant."""
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    family = app.property("cetPrivateUiFont") if app else ""
    return ('"' + PRIVATE_FONT_FAMILY + '", ' + fallback) if family == PRIVATE_FONT_FAMILY else fallback


def prepare_fonts(application, *, private_dir=None) -> None:
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
    family = _load_private_family(application, private_dir if private_dir is not None else _private_font_dir())
    application.setProperty("cetPrivateUiFont", family)
    application.setFont(QFont(family or ("Microsoft YaHei" if os.name == "nt" else "Sans Serif"), 10))

LIGHT: dict[str, str] = {
    "canvas": "#f5f4ef",
    "surface": "#eeede7",
    "text": "#202a26",
    "muted": "#66736d",
    "line": "#d5d8d0",
    "accent": "#28675b",
    "accent_text": "#ffffff",
    "accent_hover": "#20584e",
    "accent_press": "#194c43",
    "accent_soft": "rgba(40, 103, 91, 0.12)",
    "hover": "rgba(32, 42, 38, 0.055)",
    "selection": "rgba(40, 103, 91, 0.18)",
    "danger": "#b83f36",
    "danger_soft": "rgba(184, 63, 54, 0.09)",
    "success": "#28745c",
    "success_text": "#ffffff",
    "field": "#fffefa",
    "grid": "#e5e7df",
    "scroll": "#b9c0b9",
    "scroll_hover": "#909b93",
    "disabled_text": "#929c95",
    "disabled_bg": "#eeede7",
    "tooltip_bg": "#fffefa",
    "hero_bg": "#e8eee8",
    "hero_text": "#203b33",
    "hero_muted": "#5b7068",
    "hero_line": "rgba(32, 59, 51, 0.18)",
    "hero_hover": "rgba(32, 59, 51, 0.07)",
}

DARK: dict[str, str] = {
    "canvas": "#191e1b",
    "surface": "#222a26",
    "text": "#e8eee9",
    "muted": "#a1aea6",
    "line": "#3b4841",
    "accent": "#83b9a8",
    "accent_text": "#17231d",
    "accent_hover": "#9acbbb",
    "accent_press": "#6fa894",
    "accent_soft": "rgba(131, 185, 168, 0.17)",
    "hover": "rgba(232, 238, 233, 0.07)",
    "selection": "rgba(131, 185, 168, 0.26)",
    "danger": "#f08a7e",
    "danger_soft": "rgba(240, 138, 126, 0.15)",
    "success": "#83c4a5",
    "success_text": "#173127",
    "field": "#202723",
    "grid": "#2b3530",
    "scroll": "#526159",
    "scroll_hover": "#6b7c71",
    "disabled_text": "#758179",
    "disabled_bg": "#242d28",
    "tooltip_bg": "#26302b",
    "hero_bg": "#27352e",
    "hero_text": "#edf3ee",
    "hero_muted": "#bdc9c1",
    "hero_line": "rgba(237, 243, 238, 0.20)",
    "hero_hover": "rgba(237, 243, 238, 0.09)",
}

# The Nai family reference shares golden bodies and olive irises. Keep the
# gold on the cover spine; an accessible olive is the only action colour.
LIGHT.update({
    "canvas": "#faf9f4", "surface": "#f0efe7", "field": "#fffefa",
    "text": "#2b2b22", "muted": "#5c6051", "line": "#d9d9cb",
    "accent": "#496224", "accent_hover": "#3c521d", "accent_press": "#34471a",
    "accent_soft": "#e7edda", "selection": "#dee9c9",
    "notebook": "#f3edcf", "spine": "#c39a22",
})
DARK.update({
    "canvas": "#1c1e19", "surface": "#272a23", "field": "#23251f",
    "text": "#f1f0e6", "muted": "#bdc2b0", "line": "#454a3e",
    "accent": "#b7d58a", "accent_text": "#202819", "accent_hover": "#c6dfa2",
    "accent_press": "#a3c774", "accent_soft": "#363f2c", "selection": "#454f35",
    "notebook": "#353322", "spine": "#e2bd51",
})

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

QFrame#workspaceHeader {
    background: %(canvas)s;
    border-bottom: 1px solid %(line)s;
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
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 13px;
    font-weight: 600;
}

QFrame#sidebar QLabel#brand {
    font-size: 16px;
    font-weight: 600;
    color: %(text)s;
}

QFrame#notebookCover {
    background: %(notebook)s;
    border: 1px solid %(line)s;
    border-left: 5px solid %(spine)s;
    border-radius: 10px;
}
QFrame#examLine {
    background: %(field)s;
    border: 1px solid %(line)s;
    border-radius: 8px;
}
QRadioButton[choiceRadio="true"] {
    border: 1px solid transparent;
    border-radius: 10px; padding: 6px 12px; background: %(surface)s;
}
QRadioButton[choiceRadio="true"]:checked {
    background: %(accent_soft)s; color: %(accent)s;
}
QRadioButton[choiceRadio="true"]::indicator {
    width: 12px; height: 12px; border: 2px solid %(line)s; border-radius: 8px;
}
QRadioButton[choiceRadio="true"]::indicator:checked {
    background: %(accent)s; border: 2px solid %(accent)s; border-radius: 8px;
}
QRadioButton[choiceRadio="true"]:focus {
    border: 1px solid %(accent)s; text-decoration: underline;
}
QPushButton#recordLink { text-align: left; padding: 4px 16px; min-height: 44px; }
QPushButton#recordLink:focus { border: 2px solid %(accent)s; }
QPushButton[link="true"]:focus { border: 1px solid %(accent)s; }
/* --------------------------------------------------------------- cards --- */
QFrame[card="true"] {
    background: %(surface)s;
    border: 1px solid %(line)s;
    border-radius: 12px;
}

QFrame[tile="true"] {
    background: %(field)s;
    border: 1px solid %(line)s;
    border-radius: 10px;
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
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 20px;
    font-size: 14px;
}

QPushButton:enabled:hover {
    background: %(hover)s;
    color: %(accent)s;
    border-color: %(accent)s;
}

QPushButton:focus {
    background: %(accent_soft)s;
    border-color: %(accent)s;
}

QPushButton:pressed {
    background: %(accent_soft)s;
}

QPushButton:disabled {
    background: %(disabled_bg)s;
    color: %(disabled_text)s;
    border-color: %(line)s;
}

/* Native segmented options: selected and keyboard focus remain distinct. */
QPushButton[choiceOption="true"] {
    background: %(surface)s;
    color: %(muted)s;
    border: 2px solid transparent;
    border-radius: 12px;
    min-height: 18px;
    padding: 5px 9px;
}
QPushButton[choiceOption="true"]:hover {
    background: %(hover)s; color: %(text)s; border-color: transparent;
}
QPushButton[choiceOption="true"]:checked {
    background: %(accent_soft)s; color: %(accent)s;
    font-weight: 600; border-color: transparent;
}
QPushButton[choiceOption="true"]:focus,
QPushButton[choiceOption="true"]:checked:focus {
    border: 2px solid %(accent)s; text-decoration: underline;
}
QPushButton[choiceOption="true"]:disabled {
    background: %(disabled_bg)s; color: %(disabled_text)s;
}
QPushButton[choiceTrigger="true"] {
    color: %(text)s; background: %(surface)s;
    border: 2px solid transparent; border-radius: 12px; padding: 5px 12px;
}
QPushButton[choiceTrigger="true"]:focus { border: 2px solid %(accent)s; }
QFrame#choicePopup {
    border: 1px solid %(line)s; border-radius: 16px; background: %(field)s;
}
QListWidget#choiceResults {
    border: 0; background: %(field)s; color: %(text)s; outline: 0;
}
QListWidget#choiceResults::item {
    min-height: 24px; padding: 5px 8px; border: 1px solid transparent; border-radius: 8px;
}
QListWidget#choiceResults::item:selected {
    border: 1px solid %(accent)s; background: %(accent_soft)s; color: %(accent)s;
}
QLabel#choiceEmpty { color: %(muted)s; padding: 8px; }

QPushButton[primary="true"] {
    background: %(accent)s;
    color: %(accent_text)s;
    border: 1px solid %(accent)s;
    border-radius: 8px;
    font-weight: 600;
}

QPushButton[primary="true"]:enabled:hover {
    background: %(accent_hover)s;
    color: %(accent_text)s;
    border-color: %(accent_hover)s;
}

QPushButton[primary="true"]:focus {
    background: %(accent_hover)s;
    border: 2px solid %(text)s;
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
    border-radius: 8px;
}

QPushButton[danger="true"]:enabled:hover {
    background: %(danger_soft)s;
    color: %(danger)s;
    border-color: %(danger_soft)s;
}

QPushButton[success="true"] {
    background: %(success)s;
    color: %(success_text)s;
    border: 1px solid %(success)s;
    border-radius: 8px;
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

QPushButton[nav="true"]:enabled:hover {
    background: %(hover)s;
    color: %(accent)s;
}

QPushButton[success="true"]:enabled:hover {
    background: %(accent_hover)s;
    color: %(accent_text)s;
    border-color: %(accent_hover)s;
}

QPushButton[nav="true"]:enabled:focus {
    color: %(accent)s;
    text-decoration: underline;
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
    border-radius: 8px;
    padding: 8px 11px;
    selection-background-color: %(selection)s;
    selection-color: %(text)s;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus {
    border: 2px solid %(accent)s;
}

QPushButton[nav="true"]:disabled {
    background: transparent;
    color: %(disabled_text)s;
    font-weight: 400;
}

QLineEdit[error="true"], QPlainTextEdit[error="true"],
QTextEdit[error="true"], QComboBox[error="true"], QSpinBox[error="true"] {
    border: 1px solid %(danger)s;
    background: %(danger_soft)s;
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
    border-radius: 8px;
    padding: 6px;
    outline: 0;
    selection-background-color: %(accent_soft)s;
    selection-color: %(accent)s;
}

/* -------------------------------------------------------------- tables --- */
QTableWidget, QTableView {
    background: %(field)s;
    alternate-background-color: %(surface)s;
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

QRadioButton:focus, QCheckBox:focus {
    color: %(accent)s;
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

/* Settings uses the genuine Regular cut for dense labels and button rows.
 * Base controls and checked choices keep the normal theme colors and focus;
 * a filled chip, not a heavier stroke, carries the selected state. */
QWidget#settingsPage QLabel[fieldLabel="true"] {
    font-size: 15px;
    font-weight: 400;
    letter-spacing: 1px;
    color: %(text)s;
}

QWidget#settingsPage QPushButton,
QWidget#settingsPage QPushButton[choiceOption="true"]:checked {
    font-size: 15px;
    font-weight: 400;
    letter-spacing: 1px;
}
"""


def _render(palette: dict[str, str]) -> str:
    tokens: dict[str, Any] = dict(palette)
    tokens["font"] = ui_font_stack()
    sheet = _TEMPLATE % tokens
    if tokens["font"] != FONT_STACK:
        # Use the two genuine cuts; do not synthesize a semibold face.
        sheet = sheet.replace("font-weight: 600", "font-weight: 700")
        sheet = sheet.replace("QPushButton {\n", "QPushButton {\n    font-weight: 700;\n", 1)
    return sheet


LIGHT_STYLE = _render(LIGHT)
DARK_STYLE = _render(DARK)


def get_app_style(theme: str) -> str:
    """Return the full application style sheet for the selected theme."""
    dark = str(theme).strip().lower() == "dark"
    if ui_font_stack() != FONT_STACK:
        return _render(DARK if dark else LIGHT)
    return DARK_STYLE if dark else LIGHT_STYLE
