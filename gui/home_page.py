"""CET entry points and saved practice/review records."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 36, 36, 32)
        layout.setSpacing(22)
        for text, prop in (("WRITE · REFLECT · IMPROVE", "eyebrow"), ("让每一次写作，都有进步。", "title"),
                           ("输入作文，获得四六级练习与教师复核报告；图片识别作为可选入口。", "subtitle")):
            label = QLabel(text)
            label.setProperty(prop, True)
            label.setWordWrap(True)
            layout.addWidget(label)
        entries = QHBoxLayout()
        for level, detail in (("CET-4", "四级写作 · 默认至少 120 词 / 任务完成、清楚表达与基本语言准确"),
                              ("CET-6", "六级写作 · 默认至少 150 词 / 论证展开、准确表达与衔接")):
            card = QFrame()
            card.setProperty("card", True)
            box = QVBoxLayout(card)
            box.setContentsMargins(24, 24, 24, 24)
            box.setSpacing(16)
            heading = QLabel(level)
            heading.setProperty("chapterTitle", True)
            caption = QLabel(detail)
            caption.setWordWrap(True)
            caption.setMinimumHeight(60)
            button = QPushButton("开始写作  →")
            button.setProperty("primary", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, l=level: self.exam_requested.emit(l))
            for widget in (heading, caption, button):
                box.addWidget(widget)
            entries.addWidget(card)
        layout.addLayout(entries)
        flow = QLabel("01  考试与题目   →   02  文本输入（可选 OCR）   →   03  文本确认   →   04  评分报告")
        flow.setProperty("subtitle", True)
        flow.setWordWrap(True)
        layout.addWidget(flow)
        row = QHBoxLayout()
        heading = QLabel("最近记录")
        heading.setProperty("section", True)
        more = QPushButton("查看全部")
        more.clicked.connect(self.history_requested.emit)
        row.addWidget(heading)
        row.addStretch()
        row.addWidget(more)
        layout.addLayout(row)
        self.recent_layout = QVBoxLayout()
        layout.addLayout(self.recent_layout)
        settings = QPushButton("设置 · 服务商与 API Key")
        settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self.load_recent([])
    def load_recent(self, records):
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not records:
            empty = QLabel("从一篇作文开始。完成评分后，练习报告会自动保存在这里。")
            empty.setProperty("subtitle", True)
            empty.setWordWrap(True)
            self.recent_layout.addWidget(empty)
        for record in records:
            source = "学生练习" if record["usage_mode"] == "student" else "教师批改"
            title = record.get("question_summary") or record["question"][:38] or "作文草稿"
            ai = record["ai_score"] or "待评分"
            button = QPushButton(f"{record['type']} · {source}  |  {title}  |  AI {ai}")
            button.setToolTip(record["question"])
            button.clicked.connect(lambda _=False, i=record['id']: self.record_requested.emit(i))
            self.recent_layout.addWidget(button)
    def play_intro(self):
        pass
