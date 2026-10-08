"""Essay setup page: type, question, student image, and reference example."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ai.prompt import ESSAY_TYPES


class SetupPage(QWidget):
    recognition_requested = pyqtSignal(dict)
    back_requested = pyqtSignal()
    exam_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._student_image_path = ""
        self._excellent_path = ""
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(22)

        title = QLabel("01 · 考试与题目")
        title.setProperty("title", True)
        layout.addWidget(title)

        self.student_name = QLineEdit()
        self.student_name.setPlaceholderText("学生姓名（可选）")
        self.student_name.setMaximumWidth(420)
        layout.addWidget(self._field("学生姓名", self.student_name))

        mode_frame = QFrame()
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(24)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for index, (name, score) in enumerate(ESSAY_TYPES.items()):
            radio = QRadioButton(f"{name}（{score} 分）")
            if index == 0:
                radio.setChecked(True)
            self.mode_group.addButton(radio)
            self.mode_buttons[name] = radio
            mode_layout.addWidget(radio)
        mode_layout.addStretch(1)
        layout.addWidget(self._field("作文类型", mode_frame))

        input_frame = QFrame()
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(24)
        self.input_mode_group = QButtonGroup(self)
        self.ocr_mode_radio = QRadioButton("上传图片并识别手写文本")
        self.manual_mode_radio = QRadioButton("不识别，直接输入文本")
        self.manual_mode_radio.setChecked(True)
        self.input_mode_group.addButton(self.ocr_mode_radio)
        self.input_mode_group.addButton(self.manual_mode_radio)
        input_layout.addWidget(self.ocr_mode_radio)
        input_layout.addWidget(self.manual_mode_radio)
        input_layout.addStretch(1)
        layout.addWidget(self._field("识别方式", input_frame))

        self.question_edit = QTextEdit()
        self.question_edit.setPlaceholderText("请输入作文题目")
        self.question_edit.setMaximumHeight(140)
        layout.addWidget(self._field("作文题目", self.question_edit))

        self.minimum_words = QSpinBox()
        self.minimum_words.setRange(0, 5000)
        self.minimum_words.setSpecialValueText("按题目文字 / 考试默认")
        self.minimum_words.setSuffix(" 词")
        layout.addWidget(self._field("题目最低词数（可覆盖默认）", self.minimum_words))
        self.image_label = QLabel("尚未选择图片")
        self.image_label.setProperty("subtitle", True)
        self.image_label.setWordWrap(True)
        self.pick_image_btn = QPushButton("选择学生作文图片")
        self.pick_image_btn.clicked.connect(self._pick_student_image)
        layout.addWidget(
            self._field(
                "学生作文图片",
                self._pair(self.image_label, self.pick_image_btn),
            )
        )

        self.example_label = QLabel("可选：上传优秀作文作为评分参考")
        self.example_label.setProperty("subtitle", True)
        self.example_label.setWordWrap(True)
        self.pick_example_btn = QPushButton("选择优秀作文")
        self.pick_example_btn.clicked.connect(self._pick_example)
        layout.addWidget(self._field("优秀作文参考", self._pair(self.example_label, self.pick_example_btn)))

        actions = QHBoxLayout()
        back_btn = QPushButton("返回首页")
        back_btn.clicked.connect(self.back_requested.emit)
        self.start_btn = QPushButton("开始识别")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self._emit_start)
        actions.addWidget(back_btn)
        actions.addStretch(1)
        actions.addWidget(self.start_btn)
        layout.addLayout(actions)

        self.mode_notice = QLabel()
        self.mode_notice.setProperty("subtitle", True)
        self.mode_notice.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.mode_notice)
        layout.addStretch(1)

        self.mode_group.buttonClicked.connect(self._update_mode_notice)
        self.input_mode_group.buttonClicked.connect(
            self._update_input_mode_controls
        )
        for name, radio in self.mode_buttons.items():
            radio.toggled.connect(lambda checked, l=name: self.exam_changed.emit(l) if checked else None)
        self._update_mode_notice()
        self._update_input_mode_controls()

    def _field(self, label_text: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(label_text)
        label.setProperty("fieldLabel", True)
        layout.addWidget(label)
        layout.addWidget(widget)
        return wrapper

    @staticmethod
    def _pair(left: QWidget, button: QPushButton) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(left, 1)
        layout.addWidget(button)
        return wrapper

    def _pick_student_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择学生作文图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        self._student_image_path = path
        self.image_label.setText(path)
        self.image_label.setToolTip(path)

    def _pick_example(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择优秀作文",
            "",
            "文本文件 (*.txt *.md *.json);;图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        self._excellent_path = path
        self.example_label.setText(path)
        self.example_label.setToolTip(path)

    def _emit_start(self) -> None:
        if not self.question_edit.toPlainText().strip():
            QMessageBox.warning(self, "缺少题目", "请填写作文题目后继续。")
            self.question_edit.setFocus()
            return
        manual_input = self.manual_mode_radio.isChecked()
        if not manual_input and not self._student_image_path:
            QMessageBox.warning(self, "缺少图片", "请先选择学生手写作文图片。")
            return
        selected = self.mode_group.checkedButton()
        essay_type = next(
            (name for name, radio in self.mode_buttons.items() if radio is selected),
            "CET-4",
        )
        max_score = ESSAY_TYPES[essay_type]
        draft = {
            "student_name": self.student_name.text().strip(),
            "essay_type": essay_type,
            "max_score": max_score,
            "question": self.question_edit.toPlainText().strip(),
            "image_path": "" if manual_input else self._student_image_path,
            "excellent_path": self._excellent_path,
            "input_mode": "manual" if manual_input else "ocr",
            "minimum_words": self.minimum_words.value() or None,
        }
        self.recognition_requested.emit(draft)

    def _update_input_mode_controls(self, _button=None) -> None:
        manual_input = self.manual_mode_radio.isChecked()
        self.pick_image_btn.setEnabled(not manual_input)
        self.image_label.setEnabled(not manual_input)
        self.start_btn.setText(
            "直接输入作文文本" if manual_input else "开始识别"
        )
        self._update_mode_notice()

    def _update_mode_notice(self, _button=None) -> None:
        selected = self.mode_group.checkedButton()
        essay_type = next(
            (
                name
                for name, radio in self.mode_buttons.items()
                if radio is selected
            ),
            "CET-4",
        )
        max_score = ESSAY_TYPES[essay_type]
        suffix = (
            "｜直接输入文本"
            if self.manual_mode_radio.isChecked()
            else ""
        )
        self.mode_notice.setText(
            f"当前为{essay_type}模式（{max_score} 分）{suffix}"
        )
