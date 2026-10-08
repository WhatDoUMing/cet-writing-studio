"""Render native PyQt6 pages with synthetic data; never contacts AI providers."""
from pathlib import Path
import sys
import os
import json
import argparse
import tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyQt6.QtWidgets import QApplication, QScrollArea, QPushButton
from PyQt6.QtTest import QTest
from config_manager import ConfigManager
from database.sqlite import Database
from memory.manager import MemoryManager
from ocr.trocr_engine import TrOCREngine
from gui.main_window import MainWindow
from gui.styles import get_app_style
from cet_scoring import validate_report, RUBRIC_VERSIONS

TEXT = """Reading is a habit that can bring lasting benefits to college students. In my opinion, universities should encourage students to read beyond their textbooks.

First, reading helps us understand different ways of life. When we read a novel or a biography, we see familiar problems from another person's perspective. This experience can make us more thoughtful in our daily decisions. Second, regular reading builds patience. Instead of moving quickly between short videos, readers learn to stay with an idea and examine it carefully.

However, a reading programme should give students real choices. A small book club, where students can recommend books and discuss them freely, may be more effective than a compulsory reading list.

To conclude, reading can improve both knowledge and judgement. With enough choice and support, students are more likely to turn it into a lifelong habit."""
REPORT = {"score": 12, "dimension_feedback": {
    "content": "回应大学阅读习惯主题，两个论点与实施建议较完整；可加入校园实践实例。",
    "language": "表达清楚，基本语言准确；部分句式可更紧凑，避免连接词重复。",
    "structure": "引言、论证、限制条件和结论衔接顺畅，段落中心明确。"},
    "overall_comment": "任务完成较好，表达自然。补充具体论据并精炼句式，有助于提升说服力。",
    "advantages": ["观点明确，结构完整。"], "disadvantages": ["具体事例仍可展开。"],
    "grammar_errors": [],
    "sentence_upgrade": [{"original": "Second, regular reading builds patience.", "rewrite": "Regular reading also cultivates the patience needed to examine complex ideas.", "reason": "展开观点并加强衔接。"}]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    temp_root=ROOT/"work";temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ui-",dir=temp_root) as temp:
        config=ConfigManager(temp,resource_root=ROOT)
        config.set("app.reduce_motion",True)
        db=Database(config.resolve_path("paths.database"));db.connect()
        w=MainWindow(config,db,MemoryManager(config.resolve_path("paths.memory")),TrOCREngine(config.get_ocr_config()))
        w.resize(1280,900);w.show()
        report=validate_report(REPORT,15,TEXT)
        record_id=db.create_essay("练习示例", "CET-4", "Write an essay on the importance of reading. You should write at least 120 words.",
            question_summary="大学阅读习惯与终身学习",usage_mode="student",ocr_text=TEXT,submitted_text=TEXT,
            score="12",ai_score="12",report_json=json.dumps(report,ensure_ascii=False),raw_ai_report=json.dumps(REPORT,ensure_ascii=False),
            rubric_version=RUBRIC_VERSIONS["CET-4"],ai_provider="演示数据",ai_model="synthetic fixture")
        def capture(name):
            app.processEvents();QTest.qWait(100)
            w.grab().save(str(args.output/name))
        app.setStyleSheet(get_app_style("light"))
        w._navigate(0);capture("home-light.png")
        start=w.home_page.findChildren(QPushButton)[0]
        QTest.mouseMove(start,start.rect().center());capture("home-hover.png")
        QTest.mouseMove(w.nav_buttons[2],w.nav_buttons[2].rect().center());capture("locked-nav-hover.png")
        w._open_new_setup();w.setup_page.question_edit.setPlainText(db.get_essay(record_id)["question"])
        capture("setup-light.png")
        w.setup_page.ocr_mode_radio.click();capture("setup-ocr-option.png")
        w.setup_page.manual_mode_radio.click()
        w._start_recognition({"student_name":"练习示例","essay_type":"CET-4","question":db.get_essay(record_id)["question"],"input_mode":"manual"})
        w.ocr_page.set_text(TEXT);capture("text-confirmation.png")
        w._open_record_report(record_id);capture("student-report.png")
        w.mode_combo.setCurrentIndex(1);capture("teacher-report.png")
        w.score_page.reviewer_edit.setText("林老师（演示）")
        w.score_page.final_score_edit.setText("13")
        w.score_page.teacher_reason_edit.setPlainText("任务完成充分，论证展开较完整；复核后将最终分调整为 13。")
        scroll=w.score_page.findChild(QScrollArea)
        app.processEvents();scroll.ensureWidgetVisible(w.score_page.review_frame,0,10)
        capture("teacher-review.png")
        app.setStyleSheet(get_app_style("dark"));scroll.verticalScrollBar().setValue(0)
        w.mode_combo.setCurrentIndex(0);capture("student-report-dark.png")
        w._open_history();capture("history-dark.png")
        w._open_settings();capture("settings-dark.png")
        w._open_new_setup();capture("setup-dark.png")
        w.close()
    print("Native screenshots rendered from synthetic fixtures; no live AI calls.")

if __name__=="__main__":main()
