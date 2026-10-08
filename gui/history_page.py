"""Grouped essay history with filtering, detail, edit, and delete actions."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.prompt import (
    heuristic_question_summary,
    sanitize_question_summary,
)
from grading_review import REVIEW_CONFIRMED


class HistoryPage(QWidget):
    back_requested = pyqtSignal()
    edit_requested = pyqtSignal(int, object)
    delete_requested = pyqtSignal(int)
    query_changed = pyqtSignal(str, object)
    load_more_requested = pyqtSignal()
    report_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.records: list[dict[str, Any]] = []
        self.usage_mode = "student"
        self.trend_level = "CET-4"
        self._groups: dict[str, dict[str, Any]] = {}
        self._group_metadata: dict[str, dict[str, Any]] = {}
        self.total_count = 0
        self._loading_filters = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 40)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("历史记录")
        title.setProperty("title", True)
        back_btn = QPushButton("返回首页")
        back_btn.clicked.connect(self.back_requested.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(back_btn)
        layout.addLayout(header)

        self.trend_label = QLabel("暂无趋势数据")
        self.trend_label.setProperty("subtitle", True)
        self.trend_label.setWordWrap(True)
        layout.addWidget(self.trend_label)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("筛选学生、题目或摘要")
        self.search_edit.textChanged.connect(self._on_filters_changed)
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(
            self._on_filters_changed
        )
        self.exam_combo = QComboBox()
        self.mode_combo = QComboBox()
        self.review_combo = QComboBox()
        for combo, items in ((self.exam_combo, [("全部考试", None), ("CET-4", "CET-4"), ("CET-6", "CET-6")]),
                             (self.mode_combo, [("全部来源", None), ("学生练习", "student"), ("教师批改", "teacher")]),
                             (self.review_combo, [("全部审核状态", None), ("待复核", "pending"), ("已确认", "confirmed")])):
            for caption, value in items:
                combo.addItem(caption, value)
            combo.currentIndexChanged.connect(self._on_filters_changed)
            filters.addWidget(combo)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.group_combo)
        layout.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(18)
        scroll.setWidget(self.groups_container)
        layout.addWidget(scroll, 1)

        self.load_more_btn = QPushButton("加载更多")
        self.load_more_btn.clicked.connect(self.load_more_requested.emit)
        self.load_more_btn.setVisible(False)
        layout.addWidget(self.load_more_btn)

    def load_history(
        self,
        essays: list[dict[str, Any]],
        trend: list[dict[str, Any]],
    ) -> None:
        self.records = essays
        self.total_count = len(essays)
        self._group_metadata = self._metadata_from_records(essays)
        self._rebuild_groups()
        self._populate_group_filter()
        self._render_groups()
        self._update_trend(trend)
        self._refresh_load_more()

    def load_history_page(
        self,
        essays: list[dict[str, Any]],
        trend: list[dict[str, Any]],
        *,
        total_count: int,
        groups: list[dict[str, Any]],
        append: bool = False,
    ) -> None:
        """Load or append a database-filtered history page."""
        if append:
            known_ids = {int(record["id"]) for record in self.records}
            self.records.extend(
                record
                for record in essays
                if int(record["id"]) not in known_ids
            )
        else:
            self.records = list(essays)
        self.total_count = total_count
        self._group_metadata = {
            str(group.get("group_key", "")): dict(group)
            for group in groups
        }
        self._rebuild_groups()
        self._populate_group_filter()
        self._render_groups()
        self._update_trend(trend)
        self._refresh_load_more()

    def current_query(self) -> tuple[str, str | None]:
        return (
            self.search_edit.text().strip(),
            self.group_combo.currentData(),
        )

    def _on_filters_changed(self, *_args: Any) -> None:
        if self._loading_filters:
            return
        search, group_key = self.current_query()
        self.query_changed.emit(search, group_key)
        self._render_groups()

    def _refresh_load_more(self) -> None:
        remaining = max(0, self.total_count - len(self.records))
        self.load_more_btn.setVisible(remaining > 0)
        if remaining:
            self.load_more_btn.setText(
                f"加载更多（已显示 {len(self.records)} / {self.total_count}）"
            )

    def _rebuild_groups(self) -> None:
        groups: dict[str, dict[str, Any]] = {}
        for record in self.records:
            question = str(record.get("question", "")).strip()
            key = str(record.get("type", "CET-4")) + ":" + question.lower()
            group = groups.setdefault(
                key,
                {
                    "question": question,
                    "summary": self._summary(record),
                    "records": [],
                    "total_count": int(
                        self._group_metadata.get(key, {}).get(
                            "record_count", 0
                        )
                    ),
                },
            )
            group["records"].append(record)
            if not group["summary"]:
                group["summary"] = self._summary(record)
        for group in groups.values():
            group["records"].sort(
                key=lambda record: (
                    self._numeric_score(record),
                    str(record.get("time", "")),
                ),
                reverse=True,
            )
        self._groups = groups

    def _populate_group_filter(self) -> None:
        selected = self.group_combo.currentData()
        self._loading_filters = True
        try:
            self.group_combo.clear()
            self.group_combo.addItem("全部题目", None)
            metadata = self._group_metadata or self._metadata_from_records(
                self.records
            )
            for key, group in sorted(
                metadata.items(),
                key=lambda item: str(item[1].get("latest_time", "")),
                reverse=True,
            ):
                label = self._summary(group) or self._short_question(
                    str(group.get("question", ""))
                )
                self.group_combo.addItem(
                    f"{label}（{int(group.get('record_count', 0))}）",
                    key,
                )
            index = self.group_combo.findData(selected)
            if index >= 0:
                self.group_combo.setCurrentIndex(index)
        finally:
            self._loading_filters = False

    def _render_groups(self) -> None:
        if self._loading_filters:
            return
        self._clear_groups()
        query = self.search_edit.text().strip().casefold()
        selected_group = self.group_combo.currentData()

        groups = []
        for key, group in self._groups.items():
            if selected_group is not None and key != selected_group:
                continue
            records = [
                record
                for record in group["records"]
                if self._matches_search(record, group["summary"], query)
            ]
            if not records:
                continue
            records.sort(
                key=lambda record: (
                    self._numeric_score(record),
                    str(record.get("time", "")),
                ),
                reverse=True,
            )
            groups.append((group, records))

        groups.sort(
            key=lambda item: max(
                str(record.get("time", ""))
                for record in item[1]
            ),
            reverse=True,
        )
        cards: list[QWidget] = []
        for group, records in groups:
            card = self._build_group(group, records)
            self.groups_layout.addWidget(card)
            cards.append(card)
        if not groups:
            empty = QLabel("没有符合条件的历史记录")
            empty.setProperty("subtitle", True)
            self.groups_layout.addWidget(empty)
        self.groups_layout.addStretch(1)
        # No entrance animation here on purpose: the list re-renders on every
        # search keystroke (tens of times a day) and the frequency gate says
        # those get no animation. Page changes are covered by the cross-fade.

    def _clear_groups(self) -> None:
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_group(
        self,
        group: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> QWidget:
        frame = QFrame()
        frame.setProperty("card", True)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel(
            group["summary"] or self._short_question(group["question"])
        )
        title.setProperty("cardTitle", True)
        total_count = int(group.get("total_count") or len(records))
        count = QLabel(f"{total_count} 条记录")
        count.setObjectName("groupCount")
        count.setProperty("subtitle", True)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(count)
        layout.addLayout(title_row)

        table = QTableWidget(len(records), 6)
        table.setHorizontalHeaderLabels(
            ["时间", "学生姓名", "考试 / 来源 / 题目", "AI练习分 / 教师分", "审核状态", "操作"]
        )
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        table.setVerticalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel
        )
        table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        for row, record in enumerate(records):
            values = [
                str(record.get("time", "")),
                (
                    str(record["student_name"])
                    if record.get("student_name") is not None
                    else "null"
                ),
                f"{record.get('type', '')} / {'学生练习' if record.get('usage_mode') == 'student' else '教师批改'} / {record.get('question', '')}",
                self._display_score(record),
                self._review_status_text(record),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
            table.setCellWidget(
                row,
                5,
                self._record_actions(record),
            )
        table.cellDoubleClicked.connect(
            lambda row, _col, records=records: self._show_detail(
                records[row]
            )
        )
        table.resizeRowsToContents()
        row_height = table.rowHeight(0) if records else 34
        visible_rows = 1.0 if len(records) <= 1 else 1.8
        table.setFixedHeight(
            table.horizontalHeader().height()
            + int(row_height * visible_rows)
            + 4
        )
        layout.addWidget(table)
        return frame

    def _record_actions(self, record: dict[str, Any]) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        detail_btn = QPushButton("打开报告 / 复核" if self.usage_mode == "teacher" else "打开报告")
        edit_btn = QPushButton("修改")
        delete_btn = QPushButton("删除")
        delete_btn.setProperty("danger", True)
        for button in (detail_btn, edit_btn, delete_btn):
            button.setProperty("compact", True)
        detail_btn.clicked.connect(lambda: self.report_requested.emit(int(record["id"])))
        edit_btn.clicked.connect(lambda: self._edit_record(record))
        delete_btn.clicked.connect(lambda: self._delete_record(record))
        layout.addWidget(detail_btn)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)
        return wrapper

    def _show_detail(self, record: dict[str, Any]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("批改详情")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(self._format_detail(record))
        layout.addWidget(detail)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _edit_record(self, record: dict[str, Any]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("修改历史记录")
        dialog.resize(560, 360)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        student_edit = QLineEdit()
        student_edit.setText(str(record.get("student_name") or ""))
        student_edit.setPlaceholderText("如需空值请留空")
        form.addRow("学生姓名", student_edit)

        type_combo = QComboBox()
        type_combo.addItems(["CET-4", "CET-6"])
        current_type = str(record.get("type", "CET-4"))
        type_index = type_combo.findText(current_type)
        type_combo.setCurrentIndex(max(0, type_index))
        form.addRow("作文类型", type_combo)

        question_edit = QTextEdit()
        question_edit.setPlainText(str(record.get("question", "")))
        question_edit.setMaximumHeight(140)
        form.addRow("题目", question_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.edit_requested.emit(
            int(record["id"]),
            {
                "student_name": student_edit.text(),
                "essay_type": type_combo.currentText(),
                "question": question_edit.toPlainText().strip(),
            },
        )

    def _delete_record(self, record: dict[str, Any]) -> None:
        answer = QMessageBox.question(
            self,
            "删除历史记录",
            "确定删除这条批改记录吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(int(record["id"]))

    def _update_trend(self, trend: list[dict[str, Any]]) -> None:
        if not trend:
            self.trend_label.setText("暂无有效分数趋势")
            return
        first = float(trend[0]["numeric_score"])
        last = float(trend[-1]["numeric_score"])
        delta = last - first
        sign = "+" if delta >= 0 else ""
        count = len(trend)
        self.trend_label.setText(
            f"{self.trend_level} · {'AI 练习分' if self.usage_mode == 'student' else '教师确认分'} · "
            f"共 {count} 次评分。首次 {first:g} 分，最近 {last:g} 分，"
            f"提升 {sign}{delta:g} 分。"
        )

    @staticmethod
    def _summary(record: dict[str, Any]) -> str:
        summary = str(record.get("question_summary") or "").strip()
        if summary:
            cleaned = sanitize_question_summary(
                summary,
                str(record.get("question", "")),
            )
            if cleaned:
                return cleaned
        question = str(record.get("question", "")).strip()
        if not question:
            return "未提供题目"
        return heuristic_question_summary(question)

    @staticmethod
    def _short_question(question: str) -> str:
        normalized = " ".join(question.split())
        return normalized[:30] if normalized else "未提供题目"

    def _numeric_score(self, record: dict[str, Any]) -> float:
        value = record.get("ai_score") if self.usage_mode == "student" else record.get("teacher_score")
        try:
            return float(value)
        except (TypeError, ValueError):
            return -1

    def _display_score(self, record: dict[str, Any]) -> str:
        if self.usage_mode == "student":
            return str(record.get("ai_score") or "待评分")
        return str(record.get("teacher_score") or "待教师确认")

    @staticmethod
    def _review_status_text(record: dict[str, Any]) -> str:
        return (
            "已确认"
            if record.get("review_status") == REVIEW_CONFIRMED
            else "待教师确认"
        )

    @staticmethod
    def _matches_search(
        record: dict[str, Any],
        summary: str,
        query: str,
    ) -> bool:
        if not query:
            return True
        haystack = " ".join(
            [
                str(record.get("student_name") or ""),
                str(record.get("question", "")),
                summary,
            ]
        ).casefold()
        return query in haystack

    @staticmethod
    def _metadata_from_records(
        records: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        for record in records:
            question = str(record.get("question", "")).strip()
            key = str(record.get("type", "CET-4")) + ":" + question.lower()
            group = metadata.setdefault(
                key,
                {
                    "group_key": key,
                    "question": question,
                    "question_summary": record.get("question_summary", ""),
                    "record_count": 0,
                    "latest_time": "",
                },
            )
            group["record_count"] += 1
            group["latest_time"] = max(
                str(group["latest_time"]),
                str(record.get("time", "")),
            )
        return metadata

    @staticmethod
    def _format_detail(record: dict[str, Any]) -> str:
        try:
            report = json.loads(record.get("report_json") or "{}")
        except json.JSONDecodeError:
            report = {}
        lines = [
            f"时间：{record.get('time', '')}",
            f"学生姓名：{record.get('student_name') or 'null'}",
            f"作文类型：{record.get('type', '')}",
            f"题目：{record.get('question', '')}",
            f"AI建议分：{record.get('ai_score') or report.get('score', '')}",
            f"教师最终分：{str(record.get("teacher_score") or "待教师确认")}",
            f"审核状态：{HistoryPage._review_status_text(record)}",
            f"审核教师：{record.get('reviewer', '')}",
            f"审核时间：{record.get('reviewed_at', '')}",
            f"修改原因：{record.get('teacher_reason', '')}",
            f"AI服务商：{record.get('ai_provider', '')}",
            f"模型名称：{record.get('ai_model', '')}",
            f"Prompt版本：{record.get('prompt_version', '')}",
            f"评分标准版本：{record.get('rubric_version', '')}",
            f"内容诊断：{report.get('dimension_feedback', {}).get('content', '')}",
            f"语言诊断：{report.get('dimension_feedback', {}).get('language', '')}",
            f"结构诊断：{report.get('dimension_feedback', {}).get('structure', '')}",
        ]
        lines += [
            "",
            "优点：",
            *HistoryPage._format_list(report.get("advantages", [])),
            "",
            "不足：",
            *HistoryPage._format_list(report.get("disadvantages", [])),
            "",
            "语法错误：",
            *HistoryPage._format_grammar(report.get("grammar_errors", [])),
            "",
            "高级改写：",
            *HistoryPage._format_upgrades(report.get("sentence_upgrade", [])),
            "",
            f"AI建议评语：{report.get('overall_comment', '')}",
            f"教师最终评语：{record.get('teacher_comment', '')}",
            "",
            "识别文本：",
            str(record.get("ocr_text", "")),
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_list(items: list[Any]) -> list[str]:
        if not items:
            return ["无"]
        return [
            f"- {item.get('text', item) if isinstance(item, dict) else item}"
            for item in items
        ]

    @staticmethod
    def _format_grammar(items: list[Any]) -> list[str]:
        if not items:
            return ["无"]
        return [
            f"- 原句：{item.get('sentence', '')}\n"
            f"  问题：{item.get('problem', '')}\n"
            f"  正确：{item.get('correct', '')}"
            for item in items
            if isinstance(item, dict)
        ]

    @staticmethod
    def _format_upgrades(items: list[Any]) -> list[str]:
        if not items:
            return ["无"]
        return [
            f"- 原句：{item.get('original', '')}\n"
            f"  改写：{item.get('rewrite', '')}\n"
            f"  理由：{item.get('reason', '')}"
            for item in items
            if isinstance(item, dict)
        ]

    def current_filters(self):
        return {"exam_level": self.exam_combo.currentData(), "usage_mode": self.mode_combo.currentData(), "review_status": self.review_combo.currentData()}
