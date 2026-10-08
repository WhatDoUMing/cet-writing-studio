"""Handwriting recognition confirmation page."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageOps
from PyQt6.QtCore import QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cet_scoring import length_notice
from gui.styles import SPELL_HINT_COLOR
from gui.text_hints import SpellingHintService
from gui.workers import SpellCheckWorker


class OCRPage(QWidget):
    confirm_requested = pyqtSignal(str)
    re_recognize_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hint_service = SpellingHintService()
        self._current_image_path = ""
        self._busy = False
        self._exam_level = "CET-4"
        self._question = ""
        self._minimum_words = None
        self._hints_checked = False
        self._hints = []
        self._spell_check_active = False
        self._spell_check_running = False
        self._pending_final_check = False
        self._updating_text = False
        self._spell_generation = 0
        self._spell_worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(18)

        title = QLabel("03 · 文本确认")
        title.setProperty("title", True)
        layout.addWidget(title)

        self.subtitle = QLabel("核对并确认作文文本。波浪线表示系统建议检查的单词。")
        self.subtitle.setProperty("subtitle", True)
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.length_label = QLabel()
        self.length_label.setWordWrap(True)
        self.length_label.setProperty("section", True)
        layout.addWidget(self.length_label)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.image_panel = self._build_image_panel()
        splitter.addWidget(self.image_panel)
        splitter.addWidget(self._build_text_panel())
        splitter.setSizes([560, 640])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        back_btn = QPushButton("返回题目设置")
        back_btn.clicked.connect(self.back_requested.emit)
        self.re_btn = QPushButton("重新识别")
        self.re_btn.setVisible(False)
        self.re_btn.clicked.connect(self.re_recognize_requested.emit)
        self.skip_btn = QPushButton("确认原文并评分")
        self.skip_btn.setProperty("primary", True)
        self.skip_btn.clicked.connect(self._confirm)
        self.fix_btn = QPushButton("一键修正明显错误")
        self.fix_btn.clicked.connect(self._apply_safe_fixes)
        self.fix_btn.setVisible(False)
        self.check_btn = QPushButton("确定修改并拼写检查")
        self.check_btn.clicked.connect(self._handle_check)
        actions.addWidget(back_btn)
        actions.addWidget(self.re_btn)
        actions.addStretch(1)
        actions.addWidget(self.skip_btn)
        actions.addWidget(self.fix_btn)
        actions.addWidget(self.check_btn)
        layout.addLayout(actions)

    def _build_image_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel("原始作文图片")
        header.setProperty("section", True)
        layout.addWidget(header)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.image_label = QLabel("图片将在这里显示")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(200, 280)
        self.image_scroll.setWidget(self.image_label)
        layout.addWidget(self.image_scroll, 1)
        return panel

    def _build_text_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_header = QLabel("作文原文（可直接编辑）")
        self.text_header.setProperty("section", True)
        layout.addWidget(self.text_header)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("在这里粘贴或输入英文作文原文…")
        layout.addWidget(self.text_edit, 1)

        self.text_edit.textChanged.connect(self._refresh_length)
        self.text_edit.setAccessibleName("确认并编辑作文原文")
        self.text_edit.document().contentsChange.connect(
            self._on_contents_change
        )

        self._hint_format = QTextCharFormat()
        self._hint_format.setUnderlineColor(QColor(SPELL_HINT_COLOR))
        self._hint_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.WaveUnderline
        )
        self.hint_label = QLabel("未发现明显拼写问题")
        self.hint_label.setProperty("subtitle", True)
        self.hint_label.setWordWrap(True)
        hint_row = QHBoxLayout()
        self.spell_progress = QProgressBar()
        self.spell_progress.setRange(0, 0)
        self.spell_progress.setTextVisible(False)
        self.spell_progress.setFixedSize(90, 12)
        self.spell_progress.setVisible(False)
        hint_row.addWidget(self.spell_progress)
        hint_row.addWidget(self.hint_label, 1)
        layout.addLayout(hint_row)
        return panel

    def set_image(self, image_path: str | Path | None) -> None:
        if not image_path:
            self.clear_image()
            return
        self._current_image_path = str(image_path)
        self.image_panel.show()
        self.re_btn.show()
        self.text_header.setText("识别文本（可直接修改）")
        self.text_edit.setPlaceholderText("识别完成后，请核对并修改作文原文…")
        self.subtitle.setText("左侧核对原图，右侧修改识别文本，再确认原文进入评分。")
        try:
            with Image.open(self._current_image_path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((900, 1400), Image.Resampling.LANCZOS)
                raw = image.tobytes("raw", "RGB")
                qimage = QImage(
                    raw,
                    image.width,
                    image.height,
                    image.width * 3,
                    QImage.Format.Format_RGB888,
                ).copy()
        except (OSError, ValueError):
            self.image_label.setText("图片加载失败")
            return
        self.image_label.setPixmap(QPixmap.fromImage(qimage))
        self.image_label.setToolTip(self._current_image_path)

    def clear_image(self, message: str = "直接输入模式，无需图片") -> None:
        self._current_image_path = ""
        self.image_label.clear()
        self.image_label.setText(message)
        self.image_label.setToolTip("")
        self.image_panel.hide()
        self.re_btn.hide()
        self.text_header.setText("作文原文（可直接编辑）")
        self.text_edit.setPlaceholderText("在这里粘贴或输入英文作文原文…")
        self.subtitle.setText("粘贴或输入作文原文，检查词数与表达，再确认原文进入评分。")

    def set_text(self, text: str) -> None:
        self._spell_generation += 1
        self._updating_text = True
        self.text_edit.setPlainText(text)
        self._updating_text = False
        self._reset_spell_check_state()
        self._refresh_length()

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def set_busy(self, busy: bool, message: str = "识别中...") -> None:
        self._busy = busy
        self._refresh_controls()
        if busy:
            self.hint_label.setText(message)
        elif self._spell_check_running:
            self.hint_label.setText("正在检查拼写，请稍候...")
        elif self._spell_check_active:
            self._show_hint_summary()
        else:
            self._set_unchecked_hint()

    def set_notice(self, message: str) -> None:
        """Show a non-blocking workflow notice when controls are available."""
        if not self._busy and not self._spell_check_running:
            self.hint_label.setText(message)

    def _refresh_controls(self) -> None:
        disabled = self._busy or self._spell_check_running
        self.re_btn.setEnabled(not disabled and bool(self._current_image_path))
        self.skip_btn.setEnabled(not disabled)
        self.fix_btn.setEnabled(not disabled and self.fix_btn.isVisible())
        self.check_btn.setEnabled(not disabled)
        self.text_edit.setReadOnly(disabled)

    def _on_contents_change(
        self,
        position: int,
        chars_removed: int,
        chars_added: int,
    ) -> None:
        if self._updating_text or not self._spell_check_active:
            return
        delta = chars_added - chars_removed
        updated = []
        for hint in self._hints:
            if position + chars_removed <= hint.start:
                updated.append(
                    replace(
                        hint,
                        start=hint.start + delta,
                        end=hint.end + delta,
                    )
                )
            elif position >= hint.end:
                updated.append(hint)
        self._hints = updated
        self._rebuild_extra_selections()
        self._refresh_fix_button()
        if updated:
            self.hint_label.setText(
                f"剩余 {len(updated)} 处标记；提交时会重新审核。"
            )
        else:
            self.hint_label.setText(
                "已清除全部标记；提交时会重新审核。"
            )

    def _reset_spell_check_state(self) -> None:
        self._spell_check_active = False
        self._spell_check_running = False
        self._pending_final_check = False
        self._hints_checked = False
        self._hints = []
        self.spell_progress.setVisible(False)
        self.text_edit.setExtraSelections([])
        self.fix_btn.setVisible(False)
        self.fix_btn.setEnabled(True)
        self.check_btn.setText("确定修改并拼写检查")
        self._refresh_controls()
        self._set_unchecked_hint()

    def _set_unchecked_hint(self) -> None:
        if self._busy:
            return
        if self.text_edit.toPlainText():
            self.hint_label.setText(
                "修改完成后，点击“确定修改并拼写检查”。"
            )
        else:
            self.hint_label.setText("等待识别结果")

    def _handle_check(self) -> None:
        if self._spell_check_active:
            self._start_spell_check(final_check=True)
        else:
            self._spell_check_active = True
            self._start_spell_check(final_check=False)

    def _start_spell_check(self, *, final_check: bool) -> None:
        if self._spell_check_running:
            return
        text = self.text_edit.toPlainText()
        if not text.strip():
            self._hints_checked = False
            self._hints = []
            self.fix_btn.setVisible(False)
            self.check_btn.setText("确定修改并拼写检查")
            self.hint_label.setText("请先输入作文文本。")
            return

        self._pending_final_check = final_check
        self._spell_generation += 1
        generation = self._spell_generation
        self._spell_check_running = True
        self.spell_progress.setVisible(True)
        self.hint_label.setText("正在检查拼写，请稍候...")
        self._refresh_controls()

        worker = SpellCheckWorker(text)
        self._spell_worker = worker
        worker.signals.finished.connect(
            lambda hints, g=generation: self._on_spell_check_finished(
                hints,
                g,
            )
        )
        worker.signals.error.connect(
            lambda message, g=generation: self._on_spell_check_error(
                message,
                g,
            )
        )
        QThreadPool.globalInstance().start(worker)

    def _on_spell_check_finished(
        self,
        hints: list,
        generation: int,
    ) -> None:
        if generation != self._spell_generation:
            return
        self._spell_check_running = False
        self._spell_worker = None
        self.spell_progress.setVisible(False)
        self._spell_check_active = True
        self._hints_checked = True
        self._hints = hints
        self._rebuild_extra_selections()
        self._refresh_fix_button()
        self.check_btn.setText("检查完成，进入评分")
        self._refresh_controls()

        if self._pending_final_check:
            self._pending_final_check = False
            if not hints:
                self._confirm()
                return
            self.hint_label.setText(
                f"仍有 {len(hints)} 处拼写问题，请修改后再次提交。"
            )
            return
        self._show_hint_summary()

    def _on_spell_check_error(
        self,
        message: str,
        generation: int,
    ) -> None:
        if generation != self._spell_generation:
            return
        self._spell_check_running = False
        self._spell_worker = None
        self._pending_final_check = False
        self.spell_progress.setVisible(False)
        self._refresh_controls()
        self.hint_label.setText(
            f"拼写检查失败：{message}。可直接跳过检查进入评分。"
        )

    def _rebuild_extra_selections(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        document = self.text_edit.document()
        for hint in self._hints:
            cursor = QTextCursor(document)
            cursor.setPosition(hint.start)
            cursor.setPosition(hint.end, QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = self._hint_format
            selections.append(selection)
        self.text_edit.setExtraSelections(selections)

    def _refresh_fix_button(self) -> None:
        confident_count = sum(
            1 for hint in self._hints if hint.confident
        )
        self.fix_btn.setVisible(confident_count > 0)
        self.fix_btn.setEnabled(
            confident_count > 0
            and not self._busy
            and not self._spell_check_running
        )

    def _apply_safe_fixes(self) -> None:
        corrected, fixed = self.hint_service.apply_safe_corrections(
            self.text_edit.toPlainText()
        )
        if not fixed:
            self.hint_label.setText("没有可自动修正的高置信度拼写错误。")
            return
        self._spell_check_active = True
        self._updating_text = True
        self.text_edit.setPlainText(corrected)
        self._updating_text = False
        self._hints = []
        self._rebuild_extra_selections()
        self._refresh_fix_button()
        self._hints_checked = True
        self.hint_label.setText(
            f"已自动修正 {len(fixed)} 处明显拼写错误；"
            "提交时会重新审核剩余内容。"
        )

    def _show_hint_summary(self) -> None:
        hints = self._hints
        if not hints:
            self.hint_label.setText("未发现明显拼写问题")
        else:
            preview = "、".join(
                f"{h.original} → {h.suggestion}" for h in hints[:5]
            )
            more = "" if len(hints) <= 5 else f" 等 {len(hints)} 处"
            self.hint_label.setText(f"建议检查：{preview}{more}")

    def _confirm(self) -> None:
        text = self.get_text()
        if not text:
            self.hint_label.setText("请先粘贴或输入作文文本，也可选择图片识别。")
            return
        self.confirm_requested.emit(text)

    def set_context(self, level, question="", minimum_words=None):
        self._exam_level, self._question, self._minimum_words = level, question, minimum_words
        self._refresh_length()
    def _refresh_length(self):
        try:
            self.length_label.setText(length_notice(self.text_edit.toPlainText(), self._exam_level, self._question, self._minimum_words))
        except ValueError as exc:
            self.length_label.setText(str(exc))
