"""Regression coverage for the optional, offline theme and home shortcuts."""
from gui.styles import get_app_style

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from gui.home_page import HomePage, RecordLink
from gui.styles import DARK, LIGHT
from gui.theme_art import ThemeArt


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_companion_is_optional_and_local(application, tmp_path):
    art = ThemeArt(32, directory=tmp_path)
    assert not art.show_role("unknown")
    assert not art.show_role("naiwa")
    invalid = tmp_path / "naidan.png"
    invalid.write_bytes(b"not an image")
    assert not art.show_role("naidan")
    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor("gold"))
    assert image.save(str(tmp_path / "naiwa.png"))
    assert art.show_role("naiwa") and not art.isHidden()
    assert art.pixmap().width() == 2 * art.pixmap().height()
    assert not art.show_role("naigou") and art.isHidden()


def test_home_key_activation_and_exam_selection(application):
    page = HomePage()
    opened = []
    page.exam_requested.connect(opened.append)
    page.set_exam_level("CET-6")
    assert page.exam_buttons["CET-6"].property("primary")
    assert not page.exam_buttons["CET-4"].property("primary")
    for level in ("CET-6", "CET-4"):
        button = page.exam_buttons[level]
        QTest.keyClick(button, Qt.Key.Key_Space)
    assert opened == ["CET-6", "CET-4"]


def test_zero_pending_and_long_history_titles(application):
    page = HomePage()
    hits = []
    page.record_requested.connect(hits.append)
    long_title = "A&B   " * 150
    base = {"question": long_title, "type": "CET-4", "usage_mode": "student"}
    page.load_recent([dict(base, id=3, ai_score=0), dict(base, id=4, ai_score=None)])
    page.setStyleSheet(get_app_style("dark"))
    page.resize(480, 520)
    page.show()
    application.processEvents()
    rows = page.findChildren(RecordLink)
    assert all(row.height() >= 50 for row in rows)
    assert "AI 0/15" in rows[0].accessibleName()
    assert "待评分" in rows[1].accessibleName()
    assert len(rows[0].text()) < 2 * len(long_title)
    assert page.scroll.horizontalScrollBar().maximum() == 0
    rows[0].click()
    assert hits == [3]
    page.close()


def test_action_and_text_contrast_on_both_themes():
    def luminance(value):
        rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        return sum(w * (v / 12.92 if v <= .04045 else ((v + .055)/1.055) ** 2.4)
                   for w, v in zip((.2126, .7152, .0722), rgb))
    for palette in (LIGHT, DARK):
        for text, surface in (("accent_text", "accent"), ("accent_text", "accent_hover"),
                              ("muted", "canvas"), ("muted", "notebook"), ("accent", "canvas")):
            a, b = sorted((luminance(palette[text]), luminance(palette[surface])))
            assert (b + .05)/(a + .05) >= 4.5, (text, surface)

def test_recent_tooltip_keeps_full_question_with_score(application):
    page = HomePage()
    summary = "社区图书馆"
    question = "Should a community library remain open at night?\nExplain your reasoning with examples."
    page.load_recent([{"id": 8, "type": "CET-6", "usage_mode": "student", "ai_score": "11",
                       "question_summary": summary, "question": question}])
    link = page.findChild(RecordLink)
    assert summary in link.accessibleName()
    assert question not in link.text()
    assert question in link.toolTip()
    assert "AI 11/15" in link.toolTip()
