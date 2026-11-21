"""Home: choose an exam level, or reopen a saved report."""
from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from gui.theme_art import ThemeArt, role_stamp


class _CopyLabel(QLabel):
    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.Polish, QEvent.Type.FontChange, QEvent.Type.Show,
                            QEvent.Type.StyleChange, QEvent.Type.Resize) and self.text():
            lines = self.heightForWidth(max(1, self.width())) if self.wordWrap() else 0
            height = max(self.fontMetrics().height(), lines)
            if height != self.minimumHeight():
                self.setMinimumHeight(height)
        return result


def _label(text, style):
    label = _CopyLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty(style, True)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


class RecordLink(QPushButton):
    """An accessible native button with independently elided text."""

    def __init__(self, title, details, question=""):
        super().__init__()
        self.full_title = title
        self.details = details
        self.setObjectName("recordLink")
        self.setAccessibleName(f"{title}，{details}")
        self.setToolTip(f"{question or title}\n{details}")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setMinimumHeight(56)
        self._fit(320)

    def sizeHint(self):
        return QSize(160, 56)

    def minimumSizeHint(self):
        return QSize(60, 56)

    def _fit(self, width):
        fm = QFontMetrics(self.font())
        title = fm.elidedText(self.full_title, Qt.TextElideMode.ElideRight, max(8, width - 36))
        self.setText(f"{title}\n{self.details}".replace("&", "&&"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit(event.size().width())


class HomePage(QWidget):
    start_grading = pyqtSignal()
    exam_requested = pyqtSignal(str)
    record_requested = pyqtSignal(int)
    history_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll)
        body = QWidget()
        self.scroll.setWidget(body)
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(32, 28, 32, 28)
        self.body.setSpacing(16)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._fit_content)
        body.installEventFilter(self)

        cover = QFrame()
        cover.setObjectName("notebookCover")
        cover.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        cover_layout = QHBoxLayout(cover)
        cover_layout.setContentsMargins(24, 20, 24, 20)
        cover_layout.setSpacing(16)
        stack = QVBoxLayout()
        stack.setSpacing(8)
        stack.addWidget(_label("Keep  /  奶蛙写作手记", "eyebrow"))
        stack.addWidget(_label("四六级写作练习本", "title"))
        stack.addWidget(_label("先选考试级别，再输入题目和作文。手写稿也可以用图片识别。", "body"))
        cover_layout.addLayout(stack, 1)
        art = ThemeArt(144)
        art.show_role("naiwa")
        cover_layout.addWidget(art)
        self.body.addWidget(cover)

        new_section = QHBoxLayout()
        new_section.setSpacing(8)
        new_section.addWidget(role_stamp("naidan", 32))
        new_section.addWidget(_label("新建练习", "section"), 1)
        self.body.addLayout(new_section)
        self.exam_buttons = {}
        for level, name, hint in (
            ("CET-4", "英语四级", "默认至少 120 词"),
            ("CET-6", "英语六级", "默认至少 150 词"),
        ):
            row = QFrame()
            row.setObjectName("examLine")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            line = QHBoxLayout(row)
            line.setContentsMargins(16, 12, 16, 12)
            line.setSpacing(12)
            labels = QVBoxLayout()
            labels.setSpacing(4)
            labels.addWidget(_label(name, "cardTitle"))
            labels.addWidget(_label(f"{level} {hint}", "metricLabel"))
            line.addLayout(labels, 1)
            button = QPushButton("写四级作文" if level == "CET-4" else "写六级作文")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, l=level: self.exam_requested.emit(l))
            line.addWidget(button)
            self.exam_buttons[level] = button
            self.body.addWidget(row)
        self.set_exam_level("CET-4")

        self.body.addSpacing(4)
        section = QHBoxLayout()
        section.setSpacing(8)
        section.addWidget(role_stamp("naigou", 32))
        section.addWidget(_label("最近记录", "section"), 1)
        more = QPushButton("查看全部")
        more.setProperty("link", True)
        more.clicked.connect(self.history_requested.emit)
        section.addWidget(more)
        self.body.addLayout(section)
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setSpacing(4)
        self.body.addLayout(self.recent_layout)
        settings = QPushButton("设置评分服务")
        settings.setProperty("link", True)
        settings.clicked.connect(self.settings_requested.emit)
        self.body.addWidget(settings, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addStretch(1)
        self.load_recent([])

    def set_exam_level(self, current):
        for level, button in self.exam_buttons.items():
            button.setProperty("primary", level == current)
            button.style().unpolish(button)
            button.style().polish(button)

    def load_recent(self, records):
        while self.recent_layout.count():
            widget = self.recent_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        if not records:
            self.recent_layout.addWidget(_label("还没有评分记录。完成第一篇作文后，可从这里重新打开报告。", "subtitle"))
        for record in records:
            question = record.get("question") or ""
            title = record.get("question_summary") or question or "未命名作文"
            score = record.get("ai_score")
            score_text = "待评分" if score is None or score == "" else f"AI {score}/15"
            source = "学生练习" if record["usage_mode"] == "student" else "教师批改"
            details = f"{record['type']} {source} {score_text}"
            button = RecordLink(" ".join(str(title).split()), details, question=question)
            button.clicked.connect(lambda _=False, i=record["id"]: self.record_requested.emit(i))
            self.recent_layout.addWidget(button)

    def eventFilter(self, watched, event):
        if watched is self.scroll.widget() and event.type() in (
            QEvent.Type.LayoutRequest, QEvent.Type.Resize, QEvent.Type.Show
        ):
            self._layout_timer.start(0)
        return super().eventFilter(watched, event)

    def _fit_content(self):
        widget = self.scroll.widget()
        self.body.activate()
        height = max(self.body.sizeHint().height(), self.body.totalHeightForWidth(max(1, widget.width())))
        if widget.minimumHeight() != height:
            widget.setMinimumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        inset = 16 if event.size().width() < 640 else 32
        self.body.setContentsMargins(inset, 20, inset, 24)

    def play_intro(self):
        pass