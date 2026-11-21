"""Settings typography cascades without changing the option-selection contract."""
import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QFont, QFontMetricsF
from PyQt6.QtWidgets import QLabel, QPushButton, QScrollArea, QStyle, QStyleOptionButton

import config_manager
from gui.styles import PRIVATE_FONT_FAMILY, get_app_style
from tests.test_workflow_sessions import APP, make_window


class MemoryOnlySecrets:
    def __init__(self, *args, **kwargs):
        pass

    def get_secret(self, name):
        return None


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_settings_keeps_dense_ocr_copy_regular_with_room_at_800px(tmp_path, monkeypatch, theme):
    monkeypatch.setattr(config_manager, "SecretStore", MemoryOnlySecrets)
    sheet, family = APP.styleSheet(), APP.property("cetPrivateUiFont")
    # MainWindow registers an optional font and deliberately falls back when
    # absent. Check the actual style rather than pretending it was installed.
    window, db = make_window(tmp_path)
    has_private_font = APP.property("cetPrivateUiFont") == PRIVATE_FONT_FAMILY
    APP.setStyleSheet(get_app_style(theme))
    try:
        window.resize(800, 600)
        window.show()
        window._open_settings()
        APP.processEvents()
        page = window.settings_page
        selector = page.ocr_mode_combo
        online, local, manual = selector.option_buttons
        online.click()
        APP.processEvents()
        assert selector.currentData() == "online" and online.isChecked()
        assert not manual.isChecked() and page.ocr_models_btn.isEnabled()
        scroll = page.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        group_label = next(q for q in page.online_ocr_provider_field.findChildren(QLabel)
                           if q.text() == "在线手写文本识别服务商")
        for w in (group_label, online, local, manual, *page.online_ocr_provider_combo.option_buttons,
                  page.online_ocr_model_combo.open_button, page.ocr_models_btn, page.ocr_balance_btn):
            scroll.ensureWidgetVisible(w, 0, 2)
            APP.processEvents()
            font = w.font()
            assert font.weight() == QFont.Weight.Normal
            assert font.pixelSize() == 15
            assert font.letterSpacingType() == QFont.SpacingType.AbsoluteSpacing
            assert font.letterSpacing() >= 1.0
            assert scroll.viewport().rect().contains(QRect(w.mapTo(scroll.viewport(), QPoint()), w.size()))
            room = w.contentsRect()
            if isinstance(w, QPushButton):
                option = QStyleOptionButton()
                w.initStyleOption(option)
                room = w.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, w)
                if not w.icon().isNull():
                    room.setWidth(room.width() - w.iconSize().width() - 4)
            assert QFontMetricsF(font).horizontalAdvance(w.text()) <= room.width(), w.text()
        local.click()
        APP.processEvents()
        assert local.isChecked() and not online.isChecked() and selector.currentData() == "local"
        assert local.font() == online.font() and not page.ocr_models_btn.isEnabled()
        APP.setStyleSheet(get_app_style("dark" if theme == "light" else "light"))
        APP.processEvents()
        assert local.isChecked() and local.font().letterSpacing() >= 1.0
        other = QPushButton("Outside Settings")
        other.ensurePolished()
        assert other.font().pixelSize() == 14
        expected_weight = QFont.Weight.Bold if has_private_font else QFont.Weight.Normal
        assert other.font().weight() == expected_weight
    finally:
        window.close()
        db.close()
        APP.setProperty("cetPrivateUiFont", family)
        APP.setStyleSheet(sheet)
        APP.processEvents()
