"""Scoring progress and detailed report page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QIODevice, QSaveFile, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui import motion
from gui.theme_art import role_stamp
from gui.workflow_art import WorkflowArt


class ScorePage(QWidget):
    back_requested = pyqtSignal()
    dispute_requested = pyqtSignal()
    apply_corrections_requested = pyqtSignal()
    confirmation_requested = pyqtSignal(object)
    workflow_art_presented = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report: dict[str, Any] = {}
        self.usage_mode = "student"
        self._submitted_text = ""
        self._exam_level = "CET-4"
        self._loading = False
        self._review_confirmed = False
        self._build_ui()
        self.set_loading(False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self.body_layout = QVBoxLayout(content)
        self.body_layout.setContentsMargins(40, 36, 40, 40)
        self.body_layout.setSpacing(18)

        self.title = QLabel("AI 正在分析")
        self.title.setProperty("title", True)
        heading = QHBoxLayout()
        heading.setSpacing(16)
        self.report_stamp = role_stamp("naigou", 68)
        self.review_reading_art = WorkflowArt("reviewing", 76, 64)
        self.practice_completed_art = WorkflowArt("review_completed", 68, 60)
        heading.addWidget(self.report_stamp)
        heading.addWidget(self.review_reading_art)
        heading.addWidget(self.practice_completed_art)
        heading.addWidget(self.title, 1)
        self.body_layout.addLayout(heading)

        self.status = QLabel("")
        self.status.setProperty("subtitle", True)
        self.status.setWordWrap(True)
        self.body_layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(12)
        self.body_layout.addWidget(self.progress)

        self.report_container = QWidget()
        self.report_layout = QVBoxLayout(self.report_container)
        self.report_layout.setContentsMargins(0, 0, 0, 0)
        self.report_layout.setSpacing(18)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.original_panel = QWidget()
        original_layout = QVBoxLayout(self.original_panel)
        original_layout.setContentsMargins(0, 0, 18, 0)
        heading = QLabel("实际提交原文")
        heading.setProperty("section", True)
        self.original_edit = QPlainTextEdit()
        self.original_edit.setReadOnly(True)
        self.original_edit.setMinimumHeight(460)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        self.source_label.setProperty("subtitle", True)
        original_layout.addWidget(heading)
        original_layout.addWidget(self.source_label)
        original_layout.addWidget(self.original_edit)
        original_layout.addStretch()
        self.diagnosis_panel = QWidget()
        self.diagnosis_layout = QVBoxLayout(self.diagnosis_panel)
        self.diagnosis_layout.setContentsMargins(8, 0, 0, 0)
        self.diagnosis_layout.addWidget(self.report_container)
        self.splitter.addWidget(self.original_panel)
        self.splitter.addWidget(self.diagnosis_panel)
        self.splitter.setSizes([420, 560])
        self.body_layout.addWidget(self.splitter)

        self.review_frame = QFrame()
        self.review_frame.setProperty("card", True)
        review_layout = QVBoxLayout(self.review_frame)
        review_layout.setContentsMargins(24, 22, 24, 22)
        review_layout.setSpacing(12)
        review_title = QLabel("教师最终确认")
        review_title.setProperty("cardTitle", True)
        review_layout.addWidget(review_title)
        self.review_status = QLabel("待教师确认：AI 分数仅为批改建议。")
        self.review_status.setWordWrap(True)
        self.review_status.setProperty("subtitle", True)
        review_status_row = QHBoxLayout()
        review_status_row.setSpacing(8)
        self.review_completed_art = WorkflowArt("review_completed", 68, 60)
        review_status_row.addWidget(self.review_completed_art)
        review_status_row.addWidget(self.review_status, 1)
        review_layout.addLayout(review_status_row)
        review_form = QFormLayout()
        self.final_score_edit = QLineEdit()
        self.final_score_edit.setPlaceholderText("输入教师最终总分")
        review_form.addRow("教师最终分", self.final_score_edit)
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("填写审核教师姓名或工号")
        review_form.addRow("审核教师", self.reviewer_edit)
        self.teacher_comment_edit = QPlainTextEdit()
        self.teacher_comment_edit.setPlaceholderText("可修改最终教师评语")
        self.teacher_comment_edit.setMaximumHeight(120)
        review_form.addRow("教师评语", self.teacher_comment_edit)
        self.teacher_reason_edit = QPlainTextEdit()
        self.teacher_reason_edit.setPlaceholderText(
            "修改 AI 建议分或建议评语时填写原因"
        )
        self.teacher_reason_edit.setMaximumHeight(90)
        review_form.addRow("修改原因", self.teacher_reason_edit)
        review_layout.addLayout(review_form)
        self.long_term_check = QCheckBox("明确确认：将当前反馈加入本考试级别长期规则")
        self.long_term_check.setChecked(False)
        review_layout.addWidget(self.long_term_check)
        review_actions = QHBoxLayout()
        self.accept_ai_btn = QPushButton("接受AI建议并确认")
        self.accept_ai_btn.clicked.connect(
            lambda: self._emit_confirmation(accept_ai=True)
        )
        self.confirm_score_btn = QPushButton("确认最终成绩")
        self.confirm_score_btn.setProperty("primary", True)
        self.confirm_score_btn.clicked.connect(
            lambda: self._emit_confirmation(accept_ai=False)
        )
        review_actions.addWidget(self.accept_ai_btn)
        review_actions.addWidget(self.confirm_score_btn)
        review_actions.addStretch(1)
        review_layout.addLayout(review_actions)
        self.body_layout.addWidget(self.review_frame)

        self.correction_frame = QFrame()
        correction_layout = QVBoxLayout(self.correction_frame)
        correction_layout.setContentsMargins(0, 0, 0, 0)
        correction_layout.setSpacing(10)
        correction_title = QLabel("修正后的作文")
        correction_title.setProperty("cardTitle", True)
        correction_layout.addWidget(correction_title)
        self.corrected_edit = QPlainTextEdit()
        self.corrected_edit.setReadOnly(True)
        self.corrected_edit.setPlaceholderText(
            "点击“一键替换生成修正作文”后显示结果。"
        )
        self.corrected_edit.setMinimumHeight(180)
        correction_layout.addWidget(self.corrected_edit)
        self.correction_status = QLabel("")
        self.correction_status.setProperty("subtitle", True)
        self.correction_status.setWordWrap(True)
        export_status_row = QHBoxLayout()
        export_status_row.setSpacing(8)
        self.export_success_art = WorkflowArt("export_success", 64, 56)
        export_status_row.addWidget(self.export_success_art)
        export_status_row.addWidget(self.correction_status, 1)
        correction_layout.addLayout(export_status_row)
        correction_actions = QHBoxLayout()
        self.apply_corrections_btn = QPushButton("一键替换生成修正作文")
        self.apply_corrections_btn.setProperty("primary", True)
        self.apply_corrections_btn.clicked.connect(
            self.apply_corrections_requested.emit
        )
        self.copy_corrected_btn = QPushButton("复制修正作文")
        self.copy_corrected_btn.clicked.connect(self._copy_corrected)
        correction_actions.addWidget(self.apply_corrections_btn)
        correction_actions.addWidget(self.copy_corrected_btn)
        self.export_corrected_btn = QPushButton("另存为文本")
        self.export_corrected_btn.setAccessibleName("另存修正作文为文本")
        self.export_corrected_btn.clicked.connect(self._export_corrected)
        correction_actions.addWidget(self.export_corrected_btn)
        correction_actions.addStretch(1)
        correction_layout.addLayout(correction_actions)
        self.body_layout.addWidget(self.correction_frame)
        self.body_layout.addStretch(1)

        self.actions = QHBoxLayout()
        back_btn = QPushButton("返回文本确认")
        back_btn.clicked.connect(self.back_requested.emit)
        self.dispute_btn = QPushButton("评分有异议")
        self.dispute_btn.clicked.connect(self.dispute_requested.emit)
        self.actions.addWidget(back_btn)
        self.actions.addWidget(self.dispute_btn)
        self.actions.addStretch(1)
        self.body_layout.addLayout(self.actions)

    def set_loading(self, loading: bool, message: str = "AI 正在分析作文...") -> None:
        self._loading = loading
        if loading:
            self._clear_completion_art()
            for frame in (self.review_frame, self.correction_frame):
                motion.cancel_motion(frame)
        self.progress.setVisible(loading)
        has_report = bool(self.report)
        self.report_container.setVisible(not loading and has_report)
        self.splitter.setVisible(not loading and has_report)
        self.review_frame.setVisible(not loading and has_report and self.usage_mode == "teacher")
        self.correction_frame.setVisible(not loading and has_report)
        self.dispute_btn.setEnabled(not loading and has_report)
        self.apply_corrections_btn.setEnabled(not loading and has_report)
        self.copy_corrected_btn.setEnabled(not loading and has_report)
        self._refresh_export_button()
        review_enabled = not loading and has_report and not self._review_confirmed
        self.accept_ai_btn.setEnabled(review_enabled)
        self.confirm_score_btn.setEnabled(review_enabled)
        if loading:
            self.title.setText("AI 正在分析")
            self.status.setText(message)
        elif has_report:
            self.title.setText("04 学生练习报告" if self.usage_mode == "student" else "04 教师复核报告")
        else:
            self.title.setText("暂无评分结果")
        self._refresh_report_art()

    def _refresh_export_button(self) -> None:
        self.export_corrected_btn.setEnabled(
            not self._loading and bool(self.report) and bool(self.corrected_edit.toPlainText().strip())
        )

    def _refresh_report_art(self) -> None:
        completion = any(art.active for art in (
            self.practice_completed_art, self.review_completed_art, self.export_success_art,
        ))
        reviewing = self._loading or (
            bool(self.report) and self.usage_mode == "teacher" and not self._review_confirmed
        )
        reading = self.review_reading_art.set_active(reviewing and not completion)
        self.report_stamp.setVisible(self.report_stamp.role is not None and not (reading or completion))
        if reading or completion:
            self.workflow_art_presented.emit()

    def has_workflow_art(self) -> bool:
        return any(art.active for art in (
            self.review_reading_art, self.practice_completed_art,
            self.review_completed_art, self.export_success_art,
        ))

    def acknowledge_student_save(self) -> None:
        """Celebrate a successful new write, never a replay of a saved report."""
        art = self.practice_completed_art
        if self.usage_mode != "student" or self._loading or not self.report or art.active:
            return
        if art.set_active(True):
            art.play_review_once(reduced=motion.is_reduce_motion())
            self._refresh_report_art()

    def _clear_completion_art(self) -> None:
        self.practice_completed_art.set_active(False)
        self.review_completed_art.set_active(False)
        self.export_success_art.set_active(False)

    def reset_report(self, message: str = "") -> None:
        """Clear every artifact from the previous grading session."""
        self.report = {}
        self._review_confirmed = False
        self._clear_completion_art()
        for frame in (self.review_frame, self.correction_frame):
            motion.cancel_motion(frame)
        self.corrected_edit.clear()
        self.correction_status.clear()
        self.review_status.setText("待教师确认：AI 分数仅为批改建议。")
        self.long_term_check.setChecked(False)
        self.original_edit.clear()
        self.final_score_edit.clear()
        self.reviewer_edit.clear()
        self.teacher_comment_edit.clear()
        self.teacher_reason_edit.clear()
        self._clear_report()
        self.status.setText(message)
        self.set_loading(False)

    def show_report(self, report: dict[str, Any]) -> None:
        self.report = report
        self._review_confirmed = False
        self._clear_completion_art()
        self.corrected_edit.clear()
        self.correction_status.clear()
        self.set_loading(False)
        self._clear_report()

        revealed: list[QWidget] = []
        score = str(report.get("score", ""))
        score_block = self._score_block(score)
        self.report_layout.addWidget(score_block)
        revealed.append(score_block)
        self.final_score_edit.setText(score)

        self.report_layout.addWidget(self._section("整体评价", self._wrap_label(str(report.get("overall_comment", "")))))
        for key, caption in (("content", "内容与任务"), ("language", "语言运用"), ("structure", "结构与衔接")):
            self.report_layout.addWidget(self._section(caption, self._wrap_label(report["dimension_feedback"][key])))

        advantages = self._list_section("优点", report.get("advantages", []))
        self.report_layout.addWidget(advantages)
        revealed.append(advantages)
        disadvantages = self._list_section("不足", report.get("disadvantages", []))
        self.report_layout.addWidget(disadvantages)
        revealed.append(disadvantages)

        grammar_errors = report.get("grammar_errors", [])
        if grammar_errors:
            table = self._table_section("语法错误", grammar_errors)
            self.report_layout.addWidget(table)
            revealed.append(table)

        upgrades = report.get("sentence_upgrade", [])
        if upgrades:
            table = self._table_section("高级改写", upgrades)
            self.report_layout.addWidget(table)
            revealed.append(table)

        comment = str(report.get("overall_comment", "")).strip()
        self.teacher_comment_edit.setPlainText(comment)
        self.review_status.setText("待教师确认：AI 分数仅为批改建议。")
        self.report_layout.addStretch(1)
        revealed.extend([self.review_frame, self.correction_frame])
        self.original_edit.setPlainText(self._submitted_text)
        self.status.setText("练习报告已自动保存。AI 练习分用于学生趋势" if self.usage_mode == "student" else "AI 建议与教师最终分分别保存，原始报告保留")

    def _score_block(self, score: str) -> QWidget:
        """Hero-style AI score with a caption, like an Apple spec callout."""
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        caption = QLabel("AI 练习分" if self.usage_mode == "student" else "AI 建议分")
        caption.setProperty("eyebrow", True)
        score_label = QLabel(f"{score} / 15")
        score_label.setProperty("score", True)
        note = QLabel(f"{self.report.get('score_band', '')} {self.report.get('word_count', 0)} 词 {self._exam_level}")
        note.setProperty("subtitle", True)
        note.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(score_label)
        layout.addWidget(note)
        return frame

    def _emit_confirmation(self, *, accept_ai: bool) -> None:
        if not self.report or self.usage_mode != "teacher":
            return
        payload = {
            "teacher_score": (
                str(self.report.get("score", ""))
                if accept_ai
                else self.final_score_edit.text().strip()
            ),
            "teacher_comment": self.teacher_comment_edit.toPlainText().strip(),
            "teacher_reason": self.teacher_reason_edit.toPlainText().strip(),
            "reviewer": self.reviewer_edit.text().strip(),
            "accept_ai": accept_ai,
            "use_long_term": self.long_term_check.isChecked(),
        }
        self.confirmation_requested.emit(payload)

    def mark_confirmed(self, review: dict[str, Any], *, celebrate: bool = False) -> None:
        """Render saved data; only a new successful write can trigger applause."""
        self._review_confirmed = True
        self._clear_completion_art()
        score = str(review.get("teacher_score", ""))
        reviewer = str(review.get("reviewer", ""))
        self.final_score_edit.setText(score)
        self.teacher_comment_edit.setPlainText(
            str(review.get("teacher_comment", ""))
        )
        self.teacher_reason_edit.setPlainText(
            str(review.get("teacher_reason", ""))
        )
        self.reviewer_edit.setText(reviewer)
        self.review_status.setText(
            f"已由 {reviewer} 确认最终成绩：{score} 分。"
        )
        self.accept_ai_btn.setEnabled(False)
        self.confirm_score_btn.setEnabled(False)
        if celebrate and self.usage_mode == "teacher":
            self.review_completed_art.set_active(True)
            self.review_completed_art.play_review_once(reduced=motion.is_reduce_motion())
        self._refresh_report_art()

    def set_corrected_essay(
        self,
        text: str,
        applied: int,
        skipped: list[str],
    ) -> None:
        self.export_success_art.set_active(False)
        self.corrected_edit.setPlainText(text)
        self._refresh_export_button()
        self._refresh_report_art()
        if skipped:
            self.correction_status.setText(
                f"已替换 {applied} 处，另有 {len(skipped)} 处未在原文中精确"
                "匹配，已保留原文。"
            )
        else:
            self.correction_status.setText(f"已替换 {applied} 处修改。")

    def _copy_corrected(self) -> None:
        self.export_success_art.set_active(False)
        self._refresh_report_art()
        text = self.corrected_edit.toPlainText().strip()
        if not text:
            self.correction_status.setText("当前没有可复制的修正作文。")
            return
        QApplication.clipboard().setText(text)
        self.correction_status.setText("修正作文已复制到剪贴板。")

    def _export_corrected(self) -> None:
        """Save only after the user chooses a local .txt path; no implicit export."""
        self._clear_completion_art()
        self._refresh_report_art()
        text = self.corrected_edit.toPlainText()
        if self._loading or not self.report or not text.strip():
            self.correction_status.setText("当前没有可另存的修正作文。")
            return
        report = self.report
        filename, _ = QFileDialog.getSaveFileName(
            self, "另存修正作文", "修正作文.txt", "文本文件 (*.txt)"
        )
        if not filename:
            self.correction_status.setText("已取消另存，没有写入文件。")
            return
        if self._loading or self.report is not report or self.corrected_edit.toPlainText() != text:
            self.correction_status.setText("修正稿已变化，未写入任何文件。")
            return
        path = Path(filename)
        if filename.startswith(("//", "\\\\")) or not path.is_absolute() or path.suffix.casefold() != ".txt":
            self.correction_status.setText("请选择本机的 .txt 文件。")
            return
        destination = QSaveFile(str(path))
        data = text.encode("utf-8")
        if not destination.open(QIODevice.OpenModeFlag.WriteOnly):
            self.correction_status.setText("另存失败，文件未写入。请检查保存位置和权限。")
            return
        if destination.write(data) != len(data):
            destination.cancelWriting()
            self.correction_status.setText("另存失败，文件未完整写入。")
            return
        if not destination.commit():
            self.correction_status.setText("另存失败，文件未写入。请检查保存位置和权限。")
            return
        self.correction_status.setText("修正作文已保存为文本。")
        self.practice_completed_art.set_active(False)
        self.export_success_art.set_active(True)
        self._refresh_report_art()

    def _clear_report(self) -> None:
        while self.report_layout.count():
            item = self.report_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _section(self, title: str, widget: QWidget) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setProperty("section", True)
        layout.addWidget(label)
        layout.addWidget(widget)
        return frame

    def _score_tile(self, title: str, value: Any) -> QWidget:
        tile = QFrame()
        tile.setProperty("tile", True)
        tile.setMinimumWidth(148)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setProperty("metricLabel", True)
        value_label = QLabel(str(value or "--"))
        value_label.setProperty("metricValue", True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return tile

    def _list_section(self, title: str, items: list[Any]) -> QWidget:
        if not items:
            return self._section(title, QLabel("无"))
        text = "\n".join(
            f"• {item.get('text', str(item)) if isinstance(item, dict) else item}"
            for item in items
        )
        return self._section(title, self._wrap_label(text))

    def _table_section(self, title: str, rows: list[dict[str, Any]]) -> QWidget:
        headers = ["sentence", "problem", "correct"] if title == "语法错误" else ["original", "rewrite", "reason"]
        table = QTableWidget(len(rows), len(headers))
        names = {"sentence": "原句", "problem": "问题", "correct": "纠正", "original": "原句", "rewrite": "改写", "reason": "说明"}
        table.setHorizontalHeaderLabels([names[key] for key in headers])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        for row_index, row in enumerate(rows):
            for col_index, key in enumerate(headers):
                value = row.get(key, "")
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        table.resizeRowsToContents()
        return self._section(title, table)

    @staticmethod
    def _wrap_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def set_context(self, text, level, usage_mode, source_mode=None):
        if usage_mode != self.usage_mode:
            self._clear_completion_art()
        self._submitted_text, self._exam_level, self.usage_mode = text, level, usage_mode
        self.original_edit.setPlainText(text)
        source = "学生练习" if (source_mode or usage_mode) == "student" else "教师批改"
        self.source_label.setText(f"{level} 创建来源：{source}")
        self.set_loading(False)
