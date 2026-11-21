"""Private application fonts: exact registered glyphs, including real bilingual editor widgets."""
from pathlib import Path
import pytest
from PyQt6.QtGui import QFont, QRawFont, QTextLayout
from PyQt6.QtWidgets import QLabel,QLineEdit,QPlainTextEdit,QPushButton,QTextEdit
import gui.styles as styles
from tests.test_workflow_sessions import APP,make_window

SAMPLE="欢迎你奶家人 CET-4 & CET-6 Writing Grader，评分：96%"

def _runs(text,font):
    shaped=QTextLayout(text,font);shaped.beginLayout()
    line=shaped.createLine();line.setLineWidth(2048);shaped.endLayout()
    return [(run.rawFont(),list(run.glyphIndexes())) for run in shaped.glyphRuns()]

def _private_ready():
    if not all((styles._private_font_dir()/f).is_file() for f,_ in styles.PRIVATE_FONT_FILES):
        pytest.skip("Local typefaces are not included with the source-only checkout")

def test_theme_uses_real_regular_and_bold_glyphs_at_all_navigation_pages(tmp_path):
    _private_ready()
    styles.prepare_fonts(APP);APP.setStyleSheet(styles.get_app_style("light"))
    assert APP.font().family()==styles.PRIVATE_FONT_FAMILY
    fingerprint={}
    for (filename,_),weight in zip(styles.PRIVATE_FONT_FILES,(400,700)):
        raw=QRawFont(str(styles._private_font_dir()/filename),16)
        fingerprint[weight]=bytes(raw.fontTable("name"))
    w,db=make_window(tmp_path);w.resize(800,600);w.show(); APP.processEvents()
    try:
        assert w.stack.count()>=6
        for i in range(w.stack.count()):
            w.stack.setCurrentIndex(i); APP.processEvents()
            panel=w.stack.currentWidget()
            widgets=[obj for typ in (QLabel,QPushButton,QLineEdit,QPlainTextEdit,QTextEdit)
                     for obj in panel.findChildren(typ) if obj.isVisible()]
            assert widgets, i
            for obj in widgets:
                rs=_runs(SAMPLE,obj.font()); assert rs
                for face,glyphs in rs:
                    assert face.familyName()==styles.PRIVATE_FONT_FAMILY,(i,obj.objectName(),face.familyName())
                    assert face.weight() in (400,700) and bytes(face.fontTable("name"))==fingerprint[face.weight()]
                    assert glyphs and 0 not in glyphs
            assert panel.width()<=w.width()
        APP.setStyleSheet(styles.get_app_style("dark"));APP.processEvents()
        assert styles.PRIVATE_FONT_FAMILY in APP.styleSheet()
        assert all(r.familyName()==styles.PRIVATE_FONT_FAMILY for r,_ in _runs(SAMPLE,w.font()))
    finally:
        w.close(); APP.processEvents();db.close();APP.setStyleSheet(styles.get_app_style("light"))

def test_heading_body_and_action_hierarchy_are_two_actual_files():
    _private_ready();styles.prepare_fonts(APP);APP.setStyleSheet(styles.get_app_style("light"))
    for kind in ("heading","body","button"):
        q=QPushButton("开始 Start") if kind=="button" else QLabel(SAMPLE)
        q.setProperty("title",kind=="heading");q.ensurePolished()
        raw,ids=_runs(q.text(),q.font())[0]
        assert raw.familyName()==styles.PRIVATE_FONT_FAMILY and 0 not in ids
        assert (raw.weight(),raw.styleName())==((400,"Regular") if kind=="body" else (700,"Bold"))
        q.deleteLater()

@pytest.mark.parametrize("bad",["missing","forged","odd-extra"])
def test_missing_or_unverified_fonts_fall_back_as_a_unit(tmp_path,bad):
    if bad!="missing":
        for f,_ in styles.PRIVATE_FONT_FILES: (tmp_path/f).write_bytes(b"not an authorized font")
    if bad=="odd-extra": (tmp_path/"want-to-be-installed.ttf").write_bytes(b"not authorized")
    try:
        styles.prepare_fonts(APP,private_dir=tmp_path)
        assert not APP.property("cetPrivateUiFont") and APP.font().family()!=styles.PRIVATE_FONT_FAMILY
        assert styles.PRIVATE_FONT_FAMILY not in styles.get_app_style("light")
    finally:styles.prepare_fonts(APP)
