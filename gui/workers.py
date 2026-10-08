"""Qt worker objects for long-running recognition and AI tasks."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from ai.balance import query_balance
from ai.chat_api import ChatCompletionClient
from gui.text_hints import SpellingHintService


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)


class OCRWorker(QRunnable):
    """Run handwriting recognition outside the UI thread."""

    def __init__(
        self,
        engine: Any,
        image_path: str,
        progress_message: str = "正在预处理并识别手写文字...",
    ) -> None:
        super().__init__()
        self.engine = engine
        self.image_path = image_path
        self.progress_message = progress_message
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.progress.emit(self.progress_message)
            text = self.engine.recognize(self.image_path, use_lines=True)
            self.signals.finished.emit(text)
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.signals.error.emit(str(exc))


class SpellCheckWorker(QRunnable):
    """Run local dictionary spelling checks outside the UI thread."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            service = SpellingHintService()
            hints = service.find_hints(self.text[:20000])
            self.signals.finished.emit(hints)
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.signals.error.emit(str(exc))


class BalanceWorker(QRunnable):
    """Query provider balance or quota outside the UI thread."""

    def __init__(self, provider: str, api_key: str) -> None:
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(
                query_balance(self.provider, self.api_key)
            )
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.signals.error.emit(str(exc))


class QuestionSummaryWorker(QRunnable):
    """Generate a short question title without blocking the UI."""

    def __init__(
        self,
        provider: str,
        config: dict[str, Any],
        api_key: str,
        question: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.config = config
        self.api_key = api_key
        self.question = question
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            client = ChatCompletionClient(
                self.provider,
                self.config,
                api_key=self.api_key,
            )
            self.signals.finished.emit(
                client.summarize_question(self.question)
            )
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.signals.error.emit(str(exc))


class GradingWorker(QRunnable):
    """Call AI grading outside the UI thread."""

    def __init__(self, client: Any, kwargs: dict[str, Any]) -> None:
        super().__init__()
        self.client = client
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.progress.emit("正在调用 AI 模型评分...")
            report = self.client.grade_essay(**self.kwargs)
            self.signals.finished.emit(report)
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.signals.error.emit(str(exc))
