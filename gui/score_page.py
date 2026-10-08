"""Scoring progress and detailed report page."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
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


class ScorePage(QWidget):
    back_requested = pyqtSignal()
    dispute_requested = pyqtSignal()
    apply_corrections_requested = pyqtSignal()
    confirmation_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report: dict[str, Any] = {}
        self.usage_mode = "student"
        self._submitted_text = ""
        self._exam_level = "CET-4"
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
        self.body_layout.addWidget(self.title)

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
        review_layout.addWidget(self.review_status)
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
        self.diagnosis_layout.addWidget(self.review_frame)

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
        correction_layout.addWidget(self.correction_status)
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
        if loading:
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
        review_enabled = not loading and has_report
        self.accept_ai_btn.setEnabled(review_enabled)
        self.confirm_score_btn.setEnabled(review_enabled)
        if loading:
            self.title.setText("AI 正在分析")
            self.status.setText(message)
        elif has_report:
            self.title.setText("04 · 学生练习报告" if self.usage_mode == "student" else "04 · 教师复核报告")
        else:
            self.title.setText("暂无评分结果")

    def reset_report(self, message: str = "") -> None:
        """Clear every artifact from the previous grading session."""
        self.report = {}
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
        self.set_loading(False)
        self.corrected_edit.clear()
        self.correction_status.clear()
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
        if comment:
            comment_section = self._section(
                "AI建议评语", self._wrap_label(comment)
            )
            self.report_layout.addWidget(comment_section)
            revealed.append(comment_section)
        self.teacher_comment_edit.setPlainText(comment)
        self.review_status.setText("待教师确认：AI 分数仅为批改建议。")
        self.report_layout.addStretch(1)
        revealed.extend([self.review_frame, self.correction_frame])
        self.original_edit.setPlainText(self._submitted_text)
        self.status.setText("练习报告已自动保存 · AI 练习分用于学生趋势" if self.usage_mode == "student" else "AI 建议与教师最终分分别保存 · 原始报告保留")

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
        note = QLabel(f"{self.report.get('score_band', '')} · {self.report.get('word_count', 0)} 词 · {self._exam_level}")
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

    def mark_confirmed(self, review: dict[str, Any]) -> None:
        """Reflect a successfully persisted teacher confirmation."""
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

    def set_corrected_essay(
        self,
        text: str,
        applied: int,
        skipped: list[str],
    ) -> None:
        self.corrected_edit.setPlainText(text)
        if skipped:
            self.correction_status.setText(
                f"已替换 {applied} 处，另有 {len(skipped)} 处未在原文中精确"
                "匹配，已保留原文。"
            )
        else:
            self.correction_status.setText(f"已替换 {applied} 处修改。")

    def _copy_corrected(self) -> None:
        text = self.corrected_edit.toPlainText().strip()
        if not text:
            self.correction_status.setText("当前没有可复制的修正作文。")
            return
        QApplication.clipboard().setText(text)
        self.correction_status.setText("修正作文已复制到剪贴板。")

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
        headers = list(rows[0].keys()) if rows else []
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
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
        self._submitted_text, self._exam_level, self.usage_mode = text, level, usage_mode
        self.original_edit.setPlainText(text)
        source = "学生练习" if (source_mode or usage_mode) == "student" else "教师批改"
        self.source_label.setText(f"{level} · 创建来源：{source}")
        self.set_loading(False)
