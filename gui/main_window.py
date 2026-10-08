"""Main application window and page orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThreadPool, Qt
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ai.chat_api import (
    ChatCompletionClient,
    get_provider_preset,
    validate_report_scores,
)
from ai.corrections import apply_report_corrections
from ai.prompt import (
    DEFAULT_RUBRIC_VERSION,
    GRADING_PROMPT_VERSION,
    sanitize_question_summary,
)
from database.sqlite import Database
from grading_review import REVIEW_PENDING, validate_teacher_score
from gui import motion
from gui.history_page import HistoryPage
from gui.home_page import HomePage
from gui.ocr_page import OCRPage
from gui.score_page import ScorePage
from gui.settings_page import SettingsPage
from gui.setup_page import SetupPage
from gui.styles import get_app_style, prepare_fonts
from gui.workers import (
    GradingWorker,
    OCRWorker,
    QuestionSummaryWorker,
)
from logger_config import get_logger
from memory.manager import import_markdown_rules, rules_for_grading
from ocr.online_engine import OnlineOCREngine, get_online_ocr_preset
from ocr.trocr_engine import TrOCREngine
from version import APP_VERSION
from cet_scoring import ESSAY_TYPES, RUBRIC_VERSIONS, validate_level, length_requirement


log = get_logger("gui.main_window")


class MainWindow(QMainWindow):
    """Top-level window that owns the shared application state."""

    def __init__(
        self,
        config_manager,
        database,
        memory_manager,
        ocr_engine,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config_manager
        self.db = database
        self.memory = memory_manager
        self.ocr_engine = ocr_engine
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: list[Any] = []
        self._draft: dict[str, Any] = {}
        self._reference_text: str = ""
        self._active_ocr_engine: Any | None = None
        self._current_essay_id: int | None = None
        self._current_report: dict[str, Any] = {}
        self._current_graded_text = ""
        self._pending_grading: dict[str, Any] = {}
        self._revision_backup: dict[str, Any] | None = None
        self._session_token = 0
        self._job_sequence = 0
        self._active_jobs: dict[str, tuple[int, int]] = {}
        self._continue_session_from_setup = False
        self._closed = False
        self.usage_mode = str(self.config.get("app.usage_mode", "student"))
        self.exam_level = str(self.config.get("app.exam_level", "CET-4"))
        self._context_drafts = {}
        self._context_switching = False
        self._history_page_size = 100
        self._active_database_setting = self.config.get(
            "paths.database", ""
        )

        self.setWindowTitle(self.config.get("app.name"))
        self.resize(
            int(self.config.get("app.window_width", 1280)),
            int(self.config.get("app.window_height", 820)),
        )
        self.setMinimumSize(960, 640)
        self._active_theme = str(self.config.get("app.theme", "light"))
        motion.set_reduce_motion(bool(self.config.get("app.reduce_motion", False)))
        motion.reset_shutdown_state()
        try:
            import_markdown_rules(self.db, self.memory)
        except Exception:  # noqa: BLE001 - startup must not fail on migration
            log.exception("Could not import legacy Markdown rules")
        application = QApplication.instance()
        if application is not None:
            prepare_fonts(application)
            motion.install_press_feedback(application)
        self._build_ui()
        self._connect_signals()
        self._shortcuts = []
        for keys, action in (("Ctrl+1", lambda: self._leave_workflow(0)), ("Ctrl+2", self._open_new_setup),
                             ("Ctrl+3", self._return_to_ocr), ("Ctrl+H", self._open_history), ("Ctrl+,", self._open_settings)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        self._navigate(0)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.home_page = HomePage()
        self.setup_page = SetupPage()
        self.ocr_page = OCRPage()
        self.score_page = ScorePage()
        self.history_page = HistoryPage()
        self.settings_page = SettingsPage(self.config)

        for page in (
            self.home_page,
            self.setup_page,
            self.ocr_page,
            self.score_page,
            self.history_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 14, 32, 14)
        brand = QLabel("CET Writing Studio")
        brand.setProperty("section", True)
        header_layout.addWidget(brand)
        header_layout.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("使用模式")
        self.mode_combo.addItem("学生练习", "student")
        self.mode_combo.addItem("教师批改", "teacher")
        self.mode_combo.setCurrentIndex(1 if self.usage_mode == "teacher" else 0)
        self.exam_combo = QComboBox()
        self.exam_combo.setAccessibleName("考试级别")
        self.exam_combo.addItems(list(ESSAY_TYPES))
        self.exam_combo.setCurrentText(self.exam_level)
        header_layout.addWidget(self.mode_combo)
        header_layout.addWidget(self.exam_combo)
        workspace_layout.addWidget(header)
        workspace_layout.addWidget(self.stack, 1)
        root_layout.addWidget(workspace, 1)
        self.setup_page.mode_buttons[self.exam_level].setChecked(True)
        self.score_page.usage_mode = self.usage_mode

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(176)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 28, 16, 24)
        layout.setSpacing(8)

        brand = QLabel("CET\nWriting Studio")
        brand.setObjectName("brand")
        brand.setWordWrap(True)
        layout.addWidget(brand)
        layout.addSpacing(24)

        self.nav_buttons: list[QPushButton] = []
        for index, text in enumerate(
            ["首页", "开始写作", "文本确认", "历史记录"]
        ):
            button = QPushButton(text)
            button.setProperty("nav", True)
            button.setCheckable(True)
            if text == "历史记录":
                button.clicked.connect(self._open_history)
            else:
                button.clicked.connect(
                    lambda _checked=False, idx=index: (
                        self._navigate_from_sidebar(idx)
                    )
                )
            self.nav_buttons.append(button)
            layout.addWidget(button)
        settings_btn = QPushButton("设置")
        settings_btn.setProperty("nav", True)
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)
        layout.addStretch(1)

        version = QLabel(f"v{APP_VERSION}")
        version.setProperty("subtitle", True)
        layout.addWidget(version)
        return sidebar

    def _connect_signals(self) -> None:
        self.mode_combo.currentIndexChanged.connect(self._change_context)
        self.exam_combo.currentTextChanged.connect(self._change_context)
        self.setup_page.exam_changed.connect(self._select_exam)
        self.home_page.exam_requested.connect(self._start_exam)
        self.home_page.record_requested.connect(self._open_record_report)
        self.history_page.report_requested.connect(self._open_record_report)
        self.home_page.start_grading.connect(self._open_new_setup)
        self.home_page.history_requested.connect(lambda: self._open_history())
        self.home_page.settings_requested.connect(self._open_settings)

        self.setup_page.back_requested.connect(lambda: self._leave_workflow(0))
        self.setup_page.recognition_requested.connect(self._start_recognition)

        self.ocr_page.back_requested.connect(self._return_to_setup)
        self.ocr_page.re_recognize_requested.connect(self._restart_recognition)
        self.ocr_page.confirm_requested.connect(self._start_grading)

        self.score_page.back_requested.connect(self._return_to_ocr)
        self.score_page.dispute_requested.connect(self._handle_dispute)
        self.score_page.apply_corrections_requested.connect(
            self._generate_corrected_essay
        )
        self.score_page.confirmation_requested.connect(
            self._confirm_teacher_score
        )

        self.history_page.back_requested.connect(lambda: self._navigate(0))
        self.history_page.edit_requested.connect(
            self._update_history_record
        )
        self.history_page.delete_requested.connect(
            self._delete_history_record
        )
        self.history_page.query_changed.connect(
            lambda _search, _group: self._load_history_page(reset=True)
        )
        self.history_page.load_more_requested.connect(
            lambda: self._load_history_page(reset=False)
        )
        self.settings_page.back_requested.connect(lambda: self._navigate(0))
        self.settings_page.saved.connect(self._apply_runtime_settings)

    def _navigate_from_sidebar(self, index: int) -> None:
        if index == 1:
            self._open_new_setup()
            return
        if index == 2:
            self._invalidate_jobs("grading")
            self._navigate(2)
            return
        self._leave_workflow(index)

    def _open_new_setup(self) -> None:
        self._invalidate_jobs()
        self._begin_session({}, reuse_current=False)
        self._continue_session_from_setup = False
        self.setup_page.restore_draft({})
        self._navigate(1)

    def _open_settings(self) -> None:
        self._invalidate_jobs()
        self._navigate(5)

    def _leave_workflow(self, index: int) -> None:
        self._invalidate_jobs()
        self._navigate(index)

    def _return_to_setup(self) -> None:
        self._invalidate_jobs("ocr", "reference", "grading")
        self._continue_session_from_setup = self._current_essay_id is not None
        self._navigate(1)

    def _return_to_ocr(self) -> None:
        self._invalidate_jobs("grading")
        self._navigate(2)

    def _navigate(self, index: int) -> None:
        mapping = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
        page_index = mapping.get(index, 0)
        if page_index == 4:
            self._open_history()
            return
        if page_index == 0:
            self.home_page.load_recent(self.db.list_essays(limit=4, exam_level=self.exam_level))
        if page_index == 5:
            self.settings_page.load_values()
        self._switch_page(page_index)
        nav_targets = {0: 0, 1: 1, 2: 2, 4: 3}
        active_nav = nav_targets.get(page_index)
        for nav_index, button in enumerate(self.nav_buttons):
            button.setChecked(nav_index == active_nav)

    def _switch_page(self, page_index: int) -> None:
        """Cross-fade to another stack page instead of hard-cutting."""
        motion.cancel_motion(self.stack)
        self.stack.setCurrentIndex(page_index)

    def _open_history(self) -> None:
        self._invalidate_jobs()
        self._load_history_page(reset=True)
        self._switch_page(4)
        for nav_index, button in enumerate(self.nav_buttons):
            button.setChecked(nav_index == 3)

    def _load_history_page(self, *, reset: bool) -> None:
        search, group_key = self.history_page.current_query()
        offset = 0 if reset else len(self.history_page.records)
        filters = self.history_page.current_filters()
        self.history_page.usage_mode = self.usage_mode
        self.history_page.trend_level = filters.get("exam_level") or self.exam_level
        groups = self.db.list_essay_groups(search=search, **filters)
        valid_group_keys = {
            str(group.get("group_key", "")) for group in groups
        }
        if group_key is not None and group_key not in valid_group_keys:
            group_key = None
        total = self.db.count_essays(
            search=search,
            question_group=group_key,
            **filters,
        )
        essays = self.db.list_essays(
            limit=self._history_page_size,
            offset=offset,
            search=search,
            question_group=group_key,
            **filters,
        )
        self.history_page.load_history_page(
            essays,
            self.db.get_score_trend(exam_level=filters.get("exam_level") or self.exam_level, usage_mode=self.usage_mode),
            total_count=total,
            groups=groups,
            append=not reset,
        )

    def _start_recognition(self, draft: dict[str, Any]) -> None:
        try:
            validate_level(draft.get("essay_type", ""))
            if not str(draft.get("question", "")).strip():
                raise ValueError("请填写作文题目")
            length_requirement(draft["essay_type"], draft["question"], draft.get("minimum_words"))
        except ValueError as exc:
            QMessageBox.warning(self, "作文设置有误", str(exc))
            return
        draft = dict(draft, usage_mode=self.usage_mode, max_score="15")
        reuse_current = (
            self._continue_session_from_setup
            and self._current_essay_id is not None
        )
        self._begin_session(draft, reuse_current=reuse_current)
        self._continue_session_from_setup = False
        if self._draft.get("input_mode", "ocr") == "manual":
            self._active_ocr_engine = None
            self.ocr_page.clear_image()
            self.ocr_page.set_text("")
            self._navigate(2)
            self.ocr_page.set_busy(
                False,
                "请直接粘贴或输入作文文本。",
            )
            return

        self._active_ocr_engine = self._create_ocr_engine()
        self.ocr_page.set_image(self._draft["image_path"])
        self.ocr_page.set_text("")
        self._navigate(2)
        if self._active_ocr_engine is None:
            self.ocr_page.set_busy(
                False,
                "请直接粘贴或输入作文文本，然后进入评分。",
            )
            return
        self._run_ocr(self._draft["image_path"])
        self._start_reference_ocr()

    def _begin_session(
        self,
        draft: dict[str, Any],
        *,
        reuse_current: bool,
    ) -> None:
        """Start an isolated workflow generation, optionally retaining its row."""
        retained_id = self._current_essay_id if reuse_current else None
        self._session_token += 1
        self._active_jobs.clear()
        self._draft = dict(draft)
        self._draft.setdefault("usage_mode", self.usage_mode)
        self.ocr_page.set_context(draft.get("essay_type") or self.exam_level, draft.get("question", ""), draft.get("minimum_words"))
        self._reference_text = ""
        self._active_ocr_engine = None
        self._current_essay_id = retained_id
        self._current_report = {}
        self._current_graded_text = ""
        self._pending_grading = {}
        self._revision_backup = (
            self.db.get_essay(retained_id)
            if retained_id is not None
            else None
        )
        self.ocr_page.set_busy(False)
        self.score_page.reset_report()

    def _staged_record_fields(self, text: str) -> dict[str, str]:
        """Capture revision fields without changing the persisted record."""
        return {
            "student_name": str(
                self._draft.get("student_name") or ""
            ).strip(),
            "essay_type": str(self._draft.get("essay_type", "")),
            "question": str(self._draft.get("question", "")),
            "image_path": str(self._draft.get("image_path", "")),
            "ocr_text": text,
        }

    @staticmethod
    def _scoring_context_changed(
        existing: dict[str, Any],
        staged: dict[str, str],
    ) -> bool:
        return any(
            (
                str(existing.get("question", "")).strip()
                != staged["question"].strip(),
                str(existing.get("type", "")) != staged["essay_type"],
                str(existing.get("ocr_text", "")) != staged["ocr_text"],
            )
        )

    def _commit_grading_result(
        self,
        pending: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        """Commit one validated grading result as one essay-row update."""
        essay_id = pending.get("essay_id")
        if essay_id is None:
            raise RuntimeError("评分记录不存在")
        existing = self.db.get_essay(int(essay_id))
        if existing is None:
            raise RuntimeError("评分记录已不存在")

        staged = dict(pending["record_fields"])
        baseline = pending.get("baseline")
        if not isinstance(baseline, dict):
            baseline = existing
        context_changed = self._scoring_context_changed(baseline, staged)
        question = staged["question"]
        question_summary = str(
            pending.get("question_summary", "")
        ).strip()
        if not question.strip():
            question_summary = "未提供题目"
        elif not question_summary:
            question_summary = " ".join(question.split())[:30]

        self.db.update_essay(
            int(essay_id),
            student_name=staged["student_name"],
            essay_type=staged["essay_type"],
            question=question,
            question_summary=question_summary,
            image_path=staged["image_path"],
            ocr_text=staged["ocr_text"],
            submitted_text=pending["kwargs"]["student_text"],
            raw_ai_report=json.dumps(report.get("raw_ai_report", report), ensure_ascii=False),
            minimum_words=pending["kwargs"].get("minimum_words"),
            score=str(report.get("score", "")),
            ai_score=str(report.get("score", "")),
            teacher_score="",
            review_status=REVIEW_PENDING,
            teacher_comment="",
            teacher_reason="",
            reviewer="",
            reviewed_at="",
            ai_provider=str(pending.get("provider", "")),
            ai_model=str(pending.get("model", "")),
            prompt_version=str(pending.get("prompt_version", "")),
            rubric_version=str(pending.get("rubric_version", "")),
            max_score=str(pending["kwargs"].get("max_score", "")),
            report_json=json.dumps(report, ensure_ascii=False),
            feedback=(
                "" if context_changed else str(existing.get("feedback", ""))
            ),
        )

    def _new_job(self, kind: str) -> tuple[int, int]:
        self._job_sequence += 1
        token = (self._session_token, self._job_sequence)
        self._active_jobs[kind] = token
        return token

    def _is_current_job(self, kind: str, token: tuple[int, int]) -> bool:
        return (
            not self._closed
            and token[0] == self._session_token
            and self._active_jobs.get(kind) == token
        )

    def _invalidate_jobs(self, *kinds: str) -> None:
        targets = set(kinds) if kinds else set(self._active_jobs)
        grading_cancelled = "grading" in targets and "grading" in self._active_jobs
        for kind in targets:
            self._active_jobs.pop(kind, None)
        if "ocr" in targets:
            self.ocr_page.set_busy(False)
        if grading_cancelled:
            self._pending_grading = {}
            self.ocr_page.set_busy(False)
            self.score_page.reset_report("评分任务已取消，可修改后重新提交。")

    def _create_ocr_engine(self) -> Any | None:
        mode = str(self.config.get("ocr.mode", "online")).lower()
        if mode == "manual":
            return None
        if mode == "local":
            return self.ocr_engine

        provider = str(
            self.config.get("ocr.online_provider", "glm")
        ).lower()
        api_key = self.config.get_ocr_api_key(provider=provider)
        if not api_key:
            preset = get_online_ocr_preset(provider)
            QMessageBox.information(
                self,
                "未配置在线手写文本识别 API Key",
                f"未配置 {preset.label} 的 API Key，"
                "当前进入手动粘贴模式。",
            )
            return None
        online_config = dict(self.config.get("ocr", {}))
        online_config["online_provider"] = provider
        provider_config = self.config.get_ai_provider_config(provider)
        if provider_config.get("api_base"):
            online_config["online_api_base"] = provider_config["api_base"]
        return OnlineOCREngine(
            online_config,
            api_key=api_key,
        )

    def _start_reference_ocr(self) -> None:
        """Recognize an uploaded reference-essay image in the background."""
        path = self._draft.get("excellent_path", "")
        if not path or self._active_ocr_engine is None:
            return
        if Path(path).suffix.lower() not in {
            ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff",
        }:
            return
        token = self._new_job("reference")
        worker = OCRWorker(
            self._active_ocr_engine,
            path,
            "正在识别参考范文...",
        )
        worker.signals.finished.connect(
            lambda text, t=token: self._on_reference_ocr_finished(t, text)
        )
        worker.signals.error.connect(
            lambda message, t=token: self._on_reference_ocr_error(t, message)
        )
        self._track_worker(worker)
        self.thread_pool.start(worker)

    def _on_reference_ocr_finished(
        self,
        token: tuple[int, int],
        text: str,
    ) -> None:
        if not self._is_current_job("reference", token):
            log.info("Discarded stale reference OCR result")
            return
        self._active_jobs.pop("reference", None)
        self._reference_text = (text or "").strip()
        if str(self.config.get("ocr.mode", "online")).lower() == "local":
            self.ocr_page.set_notice(
                "正文已可校对，参考范文识别完成。"
            )
        log.info(
            "Reference essay recognition completed (%d chars)",
            len(self._reference_text),
        )

    def _on_reference_ocr_error(
        self,
        token: tuple[int, int],
        message: str,
    ) -> None:
        if not self._is_current_job("reference", token):
            log.info("Discarded stale reference OCR error")
            return
        self._active_jobs.pop("reference", None)
        self._reference_text = ""
        if str(self.config.get("ocr.mode", "online")).lower() == "local":
            self.ocr_page.set_notice(
                "正文已可校对；参考范文识别失败，本次评分将不使用该范文。"
            )
        log.warning("Reference essay recognition failed: %s", message)

    def _restart_recognition(self) -> None:
        if self._draft.get("input_mode", "ocr") == "manual":
            return
        if not self._draft.get("image_path"):
            return
        if self._active_ocr_engine is None:
            self.ocr_page.set_busy(
                False,
                "当前为手动粘贴模式。",
            )
            return
        self._run_ocr(self._draft["image_path"])

    def _run_ocr(self, image_path: str) -> None:
        if self._active_ocr_engine is None:
            return
        mode = str(self.config.get("ocr.mode", "online")).lower()
        progress = (
            "正在调用在线手写文本识别..."
            if mode == "online"
            else "正在识别手写作文..."
        )
        self.ocr_page.set_busy(True, progress)
        token = self._new_job("ocr")
        draft = dict(self._draft)
        reference_pending = bool(
            self._draft.get("excellent_path")
            and Path(str(self._draft.get("excellent_path"))).suffix.lower()
            in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        )
        worker_message = "正在预处理并识别手写文字..."
        if mode == "local" and reference_pending:
            worker_message = (
                "正在使用本地模型识别正文；参考范文将使用同一模型串行识别..."
            )
        worker = OCRWorker(
            self._active_ocr_engine,
            image_path,
            worker_message,
        )
        worker.signals.finished.connect(
            lambda text, t=token, d=draft: self._on_ocr_finished(t, d, text)
        )
        worker.signals.error.connect(
            lambda message, t=token: self._on_worker_error(
                "ocr", t, message
            )
        )
        worker.signals.progress.connect(
            lambda message, t=token: self._on_worker_progress(
                "ocr", t, message
            )
        )
        self._track_worker(worker)
        self.thread_pool.start(worker)

    def _on_ocr_finished(
        self,
        token: tuple[int, int],
        draft: dict[str, Any],
        text: str,
    ) -> None:
        if not self._is_current_job("ocr", token):
            log.info("Discarded stale essay OCR result")
            return
        self._active_jobs.pop("ocr", None)
        self.ocr_page.set_text(text)
        self.ocr_page.set_busy(False)
        if self._current_essay_id is None:
            self._current_essay_id = self.db.create_essay(
                student_name=str(draft.get("student_name") or ""),
                essay_type=str(draft.get("essay_type", "")),
                question=str(draft.get("question", "")),
                image_path=str(draft.get("image_path", "")),
                ocr_text=text,
                usage_mode=str(self._draft.get("usage_mode", self.usage_mode)),
                minimum_words=self._draft.get("minimum_words"),
            )
        else:
            # Existing completed records remain untouched until a validated
            # grading result commits this staged OCR text.
            self._current_report = {}
            self._current_graded_text = ""
            self.score_page.reset_report()
        if (
            str(self.config.get("ocr.mode", "online")).lower() == "local"
            and "reference" in self._active_jobs
        ):
            self.ocr_page.set_notice(
                "正文识别完成，参考范文仍在排队或识别；可先校对正文。"
            )

    def _start_grading(self, text: str) -> None:
        if "grading" in self._active_jobs:
            log.info("Ignored duplicate grading submission")
            return
        text = text.strip()
        if not text:
            QMessageBox.warning(
                self,
                "缺少作文文本",
                "请先完成手写文本识别或填写作文文本。",
            )
            return
        if not str(self._draft.get("question", "")).strip():
            QMessageBox.warning(self, "缺少题目", "请先填写作文题目。")
            self._return_to_setup()
            return
        if self._draft.get("essay_type") not in ESSAY_TYPES:
            QMessageBox.warning(self, "请选择考试", "请从 CET-4 或 CET-6 入口开始。")
            self._open_new_setup()
            return
        self.ocr_page.set_text(text)
        provider = self.config.get_ai_provider()
        preset = get_provider_preset(provider)
        api_key = self.config.get_api_key(provider=provider)
        if not api_key:
            QMessageBox.warning(
                self,
                "未配置 API Key",
                f"请先在系统设置中填写 {preset.label} API Key。",
            )
            self._navigate(5)
            return

        self._current_report = {}
        self.score_page.reset_report()
        self._current_graded_text = text
        if self._current_essay_id is None:
            self._current_essay_id = self.db.create_essay(
                student_name=str(self._draft.get("student_name") or ""),
                essay_type=str(self._draft.get("essay_type", "")),
                question=str(self._draft.get("question", "")),
                image_path=str(self._draft.get("image_path", "")),
                ocr_text=text,
                usage_mode=str(self._draft.get("usage_mode", self.usage_mode)),
                minimum_words=self._draft.get("minimum_words"),
            )
        essay_id = self._current_essay_id
        existing = self.db.get_essay(essay_id)
        if existing is None:
            QMessageBox.critical(self, "评分失败", "当前作文记录已不存在。")
            return
        token = self._new_job("grading")
        self.ocr_page.set_busy(True, "正在准备评分...")
        self.score_page.set_loading(True)
        self._navigate(3)

        kwargs = {
            "essay_type": self._draft.get("essay_type", ""),
            "max_score": "15",
            "question": self._draft.get("question", ""),
            "student_text": text,
            "minimum_words": self._draft.get("minimum_words"),
        }
        question = str(kwargs["question"]).strip()
        stored_summary = self.db.find_question_summary(question, self._draft["essay_type"])
        summary = (
            sanitize_question_summary(stored_summary, question)
            if stored_summary
            else None
        )
        if not question:
            summary = "未提供题目"
        self._pending_grading = {
            "token": token,
            "essay_id": essay_id,
            "provider": provider,
            "provider_config": self.config.get_ai_provider_config(provider),
            "api_key": api_key,
            "kwargs": kwargs,
            "record_fields": self._staged_record_fields(text),
            "baseline": dict(existing),
            "question_summary": "",
        }
        provider_config = self._pending_grading["provider_config"]
        self._pending_grading.update(
            model=str(
                provider_config.get("model") or preset.default_model
            ),
            prompt_version=str(
                self.config.get(
                    "grading.prompt_version",
                    GRADING_PROMPT_VERSION,
                )
            ),
            rubric_version=RUBRIC_VERSIONS[self._draft["essay_type"]],
        )
        if summary:
            self._stage_question_summary(self._pending_grading, question, summary)
            self._launch_grading_worker(token, self._pending_grading)
            return

        self.score_page.set_loading(
            True,
            "正在准备评分...",
        )
        summary_worker = QuestionSummaryWorker(
            provider,
            self._pending_grading["provider_config"],
            api_key,
            question,
        )
        summary_worker.signals.finished.connect(
            lambda result, t=token, p=self._pending_grading: (
                self._on_question_summary_finished(t, p, result)
            )
        )
        summary_worker.signals.error.connect(
            lambda message, t=token, p=self._pending_grading: (
                self._on_question_summary_error(t, p, message)
            )
        )
        self._track_worker(summary_worker)
        self.thread_pool.start(summary_worker)

    def _stage_question_summary(
        self,
        pending: dict[str, Any],
        question: str,
        summary: str,
    ) -> str:
        if not question:
            clean_summary = "未提供题目"
            pending["question_summary"] = clean_summary
            return clean_summary
        clean_summary = (
            sanitize_question_summary(summary, question)
            or " ".join(question.split())[:30]
            or "未提供题目"
        )
        pending["question_summary"] = clean_summary
        return clean_summary

    def _on_question_summary_finished(
        self,
        token: tuple[int, int],
        pending: dict[str, Any],
        summary: str,
    ) -> None:
        if not self._is_current_job("grading", token):
            log.info("Discarded stale question-summary result")
            return
        question = str(pending["kwargs"].get("question", ""))
        self._stage_question_summary(
            pending,
            question,
            summary or question[:30],
        )
        self._launch_grading_worker(token, pending)

    def _on_question_summary_error(
        self,
        token: tuple[int, int],
        pending: dict[str, Any],
        message: str,
    ) -> None:
        if not self._is_current_job("grading", token):
            log.info("Discarded stale question-summary error")
            return
        log.warning("Question summary generation failed: %s", message)
        question = str(pending["kwargs"].get("question", ""))
        self._stage_question_summary(
            pending,
            question,
            question[:30],
        )
        self._launch_grading_worker(token, pending)

    def _launch_grading_worker(
        self,
        token: tuple[int, int],
        pending: dict[str, Any],
    ) -> None:
        if not pending or not self._is_current_job("grading", token):
            return
        examples = self._load_reference_examples()
        memory_rules = rules_for_grading(self.db, self.memory, self._draft["essay_type"])
        kwargs = dict(pending["kwargs"])
        kwargs["examples"] = examples
        kwargs["memory_rules"] = memory_rules
        client = ChatCompletionClient(
            pending["provider"],
            pending["provider_config"],
            api_key=pending["api_key"],
        )
        self.score_page.set_loading(True, "AI 正在分析作文...")
        worker = GradingWorker(client, kwargs)
        worker.signals.finished.connect(
            lambda report, t=token, p=pending: self._on_grade_finished(
                t, p, report
            )
        )
        worker.signals.error.connect(
            lambda message, t=token: self._on_worker_error(
                "grading", t, message
            )
        )
        worker.signals.progress.connect(
            lambda message, t=token: self._on_worker_progress(
                "grading", t, message
            )
        )
        self._track_worker(worker)
        self.thread_pool.start(worker)

    def _on_grade_finished(
        self,
        token: tuple[int, int],
        pending: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        if not self._is_current_job("grading", token):
            log.info("Discarded stale grading result")
            return
        try:
            report = validate_report_scores(
                report,
                pending["kwargs"]["max_score"],
                pending["kwargs"]["student_text"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            self._on_worker_error(
                "grading",
                token,
                f"AI 评分报告分数校验失败：{exc}",
            )
            return
        try:
            self._commit_grading_result(pending, report)
        except Exception as exc:  # noqa: BLE001 - persistence boundary
            self._on_worker_error(
                "grading",
                token,
                f"评分结果保存失败：{exc}",
            )
            return
        self._active_jobs.pop("grading", None)
        self._pending_grading = {}
        self._current_report = report
        self.ocr_page.set_busy(False)
        record = self.db.get_essay(pending["essay_id"])
        self.score_page.set_context(pending["kwargs"]["student_text"], pending["kwargs"]["essay_type"], self.usage_mode, record["usage_mode"])
        self.score_page.show_report(report)
        essay_id = pending.get("essay_id")
        self._revision_backup = (
            self.db.get_essay(int(essay_id))
            if essay_id is not None
            else None
        )
        self._navigate(3)

    def _confirm_teacher_score(self, review: dict[str, Any]) -> None:
        """Validate and persist the teacher's final grading decision."""
        if self.usage_mode != "teacher":
            return
        essay_id = self._current_essay_id
        if essay_id is None or not self._current_report:
            QMessageBox.warning(self, "暂无评分", "当前没有可确认的 AI 建议报告。")
            return
        record = self.db.get_essay(essay_id)
        if record is None:
            QMessageBox.critical(self, "确认失败", "当前作文记录已不存在。")
            return
        reviewer = str(review.get("reviewer", "")).strip()
        if not reviewer:
            QMessageBox.warning(self, "缺少审核教师", "请填写审核教师姓名或工号。")
            return
        maximum = str(record.get("max_score", "")).strip()
        if not maximum:
            maximum = {
                "CET-4": "15",
                "CET-6": "15",
            }.get(str(record.get("type", "")), "")
        try:
            teacher_score = validate_teacher_score(
                review.get("teacher_score"),
                maximum,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "最终分无效", str(exc))
            return

        teacher_comment = str(review.get("teacher_comment", "")).strip()
        teacher_reason = str(review.get("teacher_reason", "")).strip()
        ai_score = str(record.get("ai_score") or record.get("score") or "")
        ai_comment = str(self._current_report.get("overall_comment", "")).strip()
        changed = teacher_score != ai_score or teacher_comment != ai_comment
        if changed and not teacher_reason:
            QMessageBox.warning(
                self,
                "缺少修改原因",
                "修改 AI 建议分或建议评语时，请填写修改原因。",
            )
            return
        try:
            self.db.confirm_essay_review(
                essay_id,
                teacher_score=teacher_score,
                teacher_comment=teacher_comment,
                teacher_reason=teacher_reason,
                reviewer=reviewer,
            )
        except Exception as exc:  # noqa: BLE001 - persistence boundary
            QMessageBox.critical(self, "确认失败", f"教师最终成绩保存失败：{exc}")
            return
        self.score_page.mark_confirmed(
            {
                "teacher_score": teacher_score,
                "teacher_comment": teacher_comment,
                "teacher_reason": teacher_reason,
                "reviewer": reviewer,
            }
        )
        self._revision_backup = self.db.get_essay(essay_id)
        if review.get("use_long_term") and record.get("feedback"):
            self._approve_feedback_rule(essay_id, str(record["feedback"]), reviewer)

    def _generate_corrected_essay(self) -> None:
        if not self._current_graded_text or not self._current_report:
            QMessageBox.warning(self, "缺少原文", "当前没有可用于替换的原文。")
            return
        result = apply_report_corrections(
            self._current_graded_text,
            self._current_report,
        )
        self.score_page.set_corrected_essay(
            result.text,
            result.applied,
            result.skipped,
        )

    def _update_history_record(
        self,
        essay_id: int,
        data: dict[str, Any],
    ) -> None:
        existing = self.db.get_essay(essay_id)
        if existing is None:
            return
        old_question = str(existing.get("question", "")).strip()
        new_question = str(data.get("question", "")).strip()
        old_type = str(existing.get("type", ""))
        new_type = str(data.get("essay_type", ""))
        scoring_context_changed = (
            old_question != new_question or old_type != new_type
        )
        summary = (
            str(existing.get("question_summary", ""))
            if old_question == new_question
            else ""
        )
        changes: dict[str, Any] = {
            "student_name": str(data.get("student_name", "")),
            "essay_type": new_type,
            "question": new_question,
            "question_summary": summary,
        }
        if scoring_context_changed:
            changes.update(
                score="",
                ai_score="",
                teacher_score="",
                review_status=REVIEW_PENDING,
                teacher_comment="",
                teacher_reason="",
                reviewer="",
                reviewed_at="",
                ai_provider="",
                ai_model="",
                prompt_version="",
                rubric_version="",
                max_score={
                    "CET-4": "15",
                    "CET-6": "15",
                }.get(new_type, ""),
                report_json="{}",
                feedback="",
            )
        self.db.update_essay(essay_id, **changes)
        if self._current_essay_id == essay_id and scoring_context_changed:
            self._current_report = {}
            self._current_graded_text = ""
            self.score_page.reset_report()
        self._open_history()

    def _delete_history_record(self, essay_id: int) -> None:
        self.db.delete_essay(essay_id)
        if self._current_essay_id == essay_id:
            self._current_essay_id = None
        self._open_history()

    def _load_reference_examples(self) -> list[dict[str, Any]]:
        examples = self.db.list_excellent_examples(
            self._draft.get("essay_type", ""), limit=5
        )
        excellent_path = self._draft.get("excellent_path", "")
        if not excellent_path:
            return examples
        path = Path(excellent_path)
        if path.suffix.lower() in {".txt", ".md", ".json"}:
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    examples.insert(
                        0,
                        {
                            "text": text,
                            "analysis": "用户本次上传的参考范文",
                            "score": "",
                            "source": str(path),
                        },
                    )
            except OSError as exc:
                log.warning("Could not read reference file %s: %s", path, exc)
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            text = self._reference_text
            if text:
                examples.insert(
                    0,
                    {
                        "text": text,
                        "analysis": "用户本次上传的参考范文（手写文本识别）",
                        "score": "",
                        "source": str(path),
                    },
                )
            else:
                QMessageBox.information(
                    self,
                    "参考范文识别中",
                    "参考范文图片正在识别，稍后重试评分即可自动带入识别结果。",
                )
        return examples

    def _on_worker_progress(
        self,
        kind: str,
        token: tuple[int, int],
        message: str,
    ) -> None:
        if not self._is_current_job(kind, token):
            return
        if kind == "ocr":
            self.ocr_page.set_busy(True, message)
        elif kind == "grading":
            self.score_page.set_loading(True, message)

    def _on_worker_error(
        self,
        kind: str,
        token: tuple[int, int],
        message: str,
    ) -> None:
        if not self._is_current_job(kind, token):
            log.info("Discarded stale %s worker error", kind)
            return
        self._active_jobs.pop(kind, None)
        if kind == "grading":
            self._pending_grading = {}
            self._current_report = {}
            self.score_page.reset_report("本次评分失败，未保存评分结果。")
        self.ocr_page.set_busy(False)
        log.error("Worker error: %s", message)
        mode = str(self.config.get("ocr.mode", "online")).lower()
        if mode == "online" and "OCR" in message:
            message += "\n\n可切换为“仅手动粘贴”后直接粘贴作文文本。"
        QMessageBox.critical(self, "处理失败", message)

    def _handle_dispute(self) -> None:
        if not self._current_report:
            QMessageBox.warning(self, "暂无评分", "当前没有可提交异议的评分报告。")
            return
        box = QMessageBox(self)
        box.setWindowTitle("评分异议")
        box.setText("请选择异议类型：")
        ocr_button = box.addButton(
            "手写文本识别错误",
            QMessageBox.ButtonRole.AcceptRole,
        )
        score_button = box.addButton("评分标准错误", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is ocr_button:
            self._navigate(2)
            return
        if clicked is score_button:
            self._collect_score_dispute()

    def _collect_score_dispute(self) -> None:
        suggested, ok = QInputDialog.getText(
            self,
            "建议分数",
            "请输入你认为更合理的分数：",
            text=str(self._current_report.get("score", "")),
        )
        if not ok or not suggested.strip():
            return
        try:
            suggested = validate_teacher_score(suggested, "15")
        except ValueError as exc:
            QMessageBox.warning(self, "建议分数有误", str(exc))
            return
        reason, ok = QInputDialog.getMultiLineText(
            self,
            "异议原因",
            "请说明评分哪里不符合标准：",
            "",
        )
        if not ok or not reason.strip():
            return
        original_score = str(self._current_report.get("score", ""))
        rule_text = self.memory.build_feedback_rule(
            original_score=original_score,
            suggested_score=suggested.strip(),
            reason=reason.strip(),
        )
        if self._current_essay_id is not None:
            self.db.update_essay(
                self._current_essay_id,
                feedback=f"建议分数：{suggested.strip()}；原因：{reason.strip()}",
            )
        if self.usage_mode == "student":
            QMessageBox.information(self, "反馈已保存", "反馈仅保存到当前练习作文。")
            return
        record = self.db.get_essay(self._current_essay_id) or {}
        if record.get("review_status") != "confirmed":
            QMessageBox.information(self, "反馈已保存", "完成教师复核后，可明确确认加入本级别长期规则。")
            return
        use_long_term = QMessageBox.question(
            self,
            "是否写入长期规则",
            "本次异议已保存到当前作文。是否同时写入长期评分规则？\n\n"
            "长期规则会影响后续学生的 AI 评分建议，请仅在教师复核后确认。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if use_long_term == QMessageBox.StandardButton.Yes:
            reviewer = ""
            if self._current_essay_id is not None:
                record = self.db.get_essay(self._current_essay_id) or {}
                reviewer = str(record.get("reviewer", ""))
            # The database row is what the grading prompt reads (it carries the
            # enable/disable state); the Markdown file stays a readable mirror.
            self._approve_feedback_rule(self._current_essay_id, rule_text, reviewer)
            QMessageBox.information(
                self,
                "长期规则已保存",
                "该条异议已写入长期规则，后续可基于规则状态增加停用或删除管理。",
            )
        else:
            QMessageBox.information(
                self,
                "本次反馈已保存",
                "反馈仅保存在当前作文中，未影响后续学生。",
            )

    def _select_exam(self, level):
        self.exam_combo.setCurrentText(level)

    def _start_exam(self, level):
        self.exam_combo.setCurrentText(level)
        self._open_new_setup()

    def _change_context(self, *_args):
        if self._context_switching:
            return
        new_mode, new_level = self.mode_combo.currentData(), self.exam_combo.currentText()
        if (new_mode, new_level) == (self.usage_mode, self.exam_level):
            return
        self._context_switching = True
        try:
            key = (self.usage_mode, self.exam_level)
            self._context_drafts[key] = (dict(self._draft), self.ocr_page.get_text(), self.setup_page.capture_draft())
            on_report = self.stack.currentIndex() == 3 and bool(self._current_report) and new_level == self.exam_level
            self._invalidate_jobs()
            self.usage_mode, self.exam_level = new_mode, new_level
            self.config.set("app.usage_mode", new_mode)
            self.config.set("app.exam_level", new_level)
            self.config.save()
            self.setup_page.mode_buttons[new_level].setChecked(True)
            self.history_page.usage_mode = new_mode
            if on_report:
                record = self.db.get_essay(self._current_essay_id) or {}
                self.score_page.set_context(self._current_graded_text, new_level, new_mode, record.get("usage_mode"))
                if record.get("review_status") == "confirmed":
                    self.score_page.mark_confirmed(record)
            else:
                draft, text, setup = self._context_drafts.get((new_mode, new_level), ({}, "", {}))
                self._begin_session(draft, reuse_current=False)
                self.ocr_page.set_text(text)
                self.setup_page.restore_draft(setup)
                if self.stack.currentIndex() in (1, 2, 3):
                    self._navigate(2 if draft and text else 1)
                elif self.stack.currentIndex() == 4:
                    self._load_history_page(reset=True)
            self.home_page.load_recent(self.db.list_essays(limit=4, exam_level=new_level))
        finally:
            self._context_switching = False

    def _open_record_report(self, essay_id):
        record = self.db.get_essay(essay_id)
        if not record:
            return
        try:
            text = record.get("submitted_text") or record["ocr_text"]
            report = validate_report_scores(json.loads(record["report_json"]), "15", text)
        except (ValueError, TypeError):
            QMessageBox.information(self, "暂无有效报告", "这是未完成评分的草稿，请从开始写作继续。")
            return
        self._invalidate_jobs()
        self.exam_combo.setCurrentText(record["type"])
        self._begin_session({"essay_type": record["type"], "max_score": "15", "question": record["question"],
                             "usage_mode": record["usage_mode"], "student_name": record["student_name"],
                             "image_path": record["image_path"], "input_mode": "manual", "minimum_words": record.get("minimum_words")}, reuse_current=False)
        self._current_essay_id = essay_id
        self._current_report, self._current_graded_text = report, text
        self._revision_backup = record
        self.ocr_page.set_text(text)
        self.ocr_page.set_image(record["image_path"])
        self.score_page.set_context(text, record["type"], self.usage_mode, record["usage_mode"])
        self.score_page.show_report(report)
        if record["review_status"] == "confirmed":
            self.score_page.mark_confirmed(record)
        self._navigate(3)

    def _approve_feedback_rule(self, essay_id, content, reviewer):
        record = self.db.get_essay(essay_id)
        if self.usage_mode != "teacher" or not record or record["review_status"] != "confirmed":
            raise ValueError("长期规则需要教师明确确认且作文已复核")
        level = record["type"]
        if not any(r["source_essay_id"] == essay_id and r["content"] == content for r in self.db.list_feedback_rules(exam_level=level)):
            self.db.add_feedback_rule(content, source_essay_id=essay_id, reviewer=reviewer, exam_level=level)
            from memory.manager import MemoryManager
            mirror = MemoryManager(self.memory.path.with_name(f"{level}-rules.md"))
            mirror.append_rule(content)

    def _track_worker(self, worker: Any) -> None:
        self._workers.append(worker)
        worker.signals.finished.connect(
            lambda _result=None, w=worker: self._workers.remove(w)
            if w in self._workers
            else None
        )
        worker.signals.error.connect(
            lambda _message=None, w=worker: self._workers.remove(w)
            if w in self._workers
            else None
        )

    def _apply_runtime_settings(self) -> None:
        """Apply path, local OCR model, theme, and motion changes immediately."""
        motion.set_reduce_motion(bool(self.config.get("app.reduce_motion", False)))
        app = QApplication.instance()
        if app is not None:
            theme = str(self.config.get("app.theme", "light"))
            app.setStyleSheet(get_app_style(theme))
            if theme != self._active_theme:
                # Ease the light/dark brightness jump instead of hard-cutting it.
                self._active_theme = theme
                motion.theme_crossfade(self.centralWidget())

        self.mode_combo.setCurrentIndex(1 if self.config.get("app.usage_mode", "student") == "teacher" else 0)
        self._switch_database_from_settings()
        self.ocr_engine = TrOCREngine(self.config.get_ocr_config())

    def _switch_database_from_settings(self) -> None:
        """Switch databases only after the replacement is fully initialized."""
        previous = self.db
        previous_setting = self._active_database_setting
        requested_setting = self.config.get("paths.database", "")
        replacement: Database | None = None
        try:
            configured_path = self.config.resolve_path("paths.database")
            configured_key = os.path.normcase(
                os.path.normpath(str(configured_path.resolve(strict=False)))
            )
            current_key = os.path.normcase(
                os.path.normpath(str(previous.db_path.resolve(strict=False)))
            )
            if configured_key == current_key:
                self._active_database_setting = requested_setting
                return
            replacement = Database(configured_path)
            replacement.connect()
        except Exception as exc:  # noqa: BLE001 - settings boundary
            if replacement is not None:
                try:
                    replacement.close()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    log.exception("Could not close failed replacement database")
            restore_error = ""
            try:
                self.config.set("paths.database", previous_setting)
                self.config.save()
                self.settings_page.load_values()
            except Exception as restore_exc:  # noqa: BLE001 - UI boundary
                restore_error = f"；恢复配置文件时又发生错误：{restore_exc}"
            QMessageBox.critical(
                self,
                "数据库切换失败",
                f"新数据库路径未能打开，应用将继续使用原数据库：{exc}"
                f"{restore_error}",
            )
            return

        assert replacement is not None
        self.db = replacement
        self._active_database_setting = requested_setting
        try:
            previous.close()
        except Exception:  # noqa: BLE001 - replacement is already active
            log.exception("Could not close previous database after switch")
        self._begin_session({}, reuse_current=False)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self._closed = True
        self._session_token += 1
        self._active_jobs.clear()
        self._pending_grading = {}
        motion.shutdown(QApplication.instance())
        self.db.close()
        super().closeEvent(event)
