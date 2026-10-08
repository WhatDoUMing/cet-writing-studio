"""System settings page for API key, model, and paths."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ai.chat_api import PROVIDER_PRESETS, get_provider_preset
from ocr.online_engine import (
    ONLINE_OCR_PRESETS,
    get_online_ocr_preset,
)
from gui.workers import BalanceWorker


class SettingsPage(QWidget):
    saved = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, config_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config_manager
        self._active_provider = "glm"
        self._provider_models: dict[str, str] = {}
        self._loading_provider = False
        self._balance_workers: list[BalanceWorker] = []
        self._build_ui()
        self.load_values()

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
        layout.setContentsMargins(40, 36, 40, 40)
        layout.setSpacing(22)

        title = QLabel("CET Writing Studio · 设置")
        title.setProperty("title", True)
        layout.addWidget(title)

        self.provider_combo = QComboBox()
        for preset in PROVIDER_PRESETS.values():
            self.provider_combo.addItem(preset.label, preset.key)
        self.provider_combo.currentIndexChanged.connect(
            self._on_provider_changed
        )
        layout.addWidget(self._field("AI 服务商", self.provider_combo))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.balance_btn = QPushButton("检测余额")
        self.balance_btn.clicked.connect(self._check_scoring_balance)
        layout.addWidget(
            self._field(
                "API Key",
                self._pair(self.api_key_edit, self.balance_btn),
            )
        )

        api_note = QLabel(
            "API Key 按服务商分别存入 Windows 凭据管理器，"
            "普通配置文件中不保存明文。"
        )
        api_note.setProperty("subtitle", True)
        api_note.setWordWrap(True)
        layout.addWidget(api_note)

        self.model_edit = QLineEdit()
        layout.addWidget(self._field("模型名称", self.model_edit))

        self.ocr_mode_combo = QComboBox()
        self.ocr_mode_combo.addItem("在线手写文本识别（推荐）", "online")
        self.ocr_mode_combo.addItem("本地手写文本识别", "local")
        self.ocr_mode_combo.addItem("仅手动粘贴", "manual")
        self.ocr_mode_combo.currentIndexChanged.connect(
            self._on_ocr_mode_changed
        )
        layout.addWidget(
            self._field("手写文本识别模式", self.ocr_mode_combo)
        )

        self.online_ocr_provider_combo = QComboBox()
        for preset in ONLINE_OCR_PRESETS.values():
            self.online_ocr_provider_combo.addItem(
                preset.label, preset.key
            )
        self.online_ocr_provider_combo.currentIndexChanged.connect(
            self._on_online_ocr_provider_changed
        )
        self.online_ocr_provider_field = self._field(
            "在线手写文本识别服务商",
            self.online_ocr_provider_combo,
        )
        layout.addWidget(self.online_ocr_provider_field)

        self.online_ocr_model_edit = QLineEdit()
        self.online_ocr_model_field = self._field(
            "在线手写文本识别模型",
            self.online_ocr_model_edit,
        )
        layout.addWidget(self.online_ocr_model_field)

        self.ocr_api_key_edit = QLineEdit()
        self.ocr_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ocr_api_key_field = self._field(
            "在线手写文本识别 API Key",
            self._pair(
                self.ocr_api_key_edit,
                self._make_ocr_balance_button(),
            ),
        )
        layout.addWidget(self.ocr_api_key_field)

        online_key_note = QLabel(
            "在线识别可单独配置 API Key；未单独配置时回退使用评分模型"
            "同供应商的 Key。识别失败时可切换为“仅手动粘贴”。"
        )
        online_key_note.setProperty("subtitle", True)
        online_key_note.setWordWrap(True)
        layout.addWidget(online_key_note)

        self.ocr_model_edit = QLineEdit()
        self.local_ocr_model_field = self._field(
            "本地手写文本识别模型名称或路径",
            self.ocr_model_edit,
        )
        layout.addWidget(self.local_ocr_model_field)

        self.database_edit = QLineEdit()
        layout.addWidget(self._field("数据库路径", self.database_edit))

        self.usage_mode_combo = QComboBox()
        self.usage_mode_combo.addItem("学生练习", "student")
        self.usage_mode_combo.addItem("教师批改", "teacher")
        layout.addWidget(self._field("默认 / 上次使用模式", self.usage_mode_combo))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["浅色", "深色"])
        layout.addWidget(self._field("主题", self.theme_combo))

        self.reduce_motion_check = QCheckBox("减少动效（关闭页面淡入与按钮反馈）")
        layout.addWidget(self.reduce_motion_check)

        actions = QHBoxLayout()
        back_btn = QPushButton("返回首页")
        back_btn.clicked.connect(self.back_requested.emit)
        clear_key_btn = QPushButton("清除 API Key")
        clear_key_btn.setProperty("danger", True)
        clear_key_btn.clicked.connect(self._clear_api_key)
        clear_ocr_key_btn = QPushButton("清除识别 Key")
        clear_ocr_key_btn.setProperty("danger", True)
        clear_ocr_key_btn.clicked.connect(self._clear_ocr_api_key)
        save_btn = QPushButton("保存设置")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save)
        actions.addWidget(back_btn)
        actions.addWidget(clear_key_btn)
        actions.addWidget(clear_ocr_key_btn)
        actions.addStretch(1)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        layout.addStretch(1)

    def _make_ocr_balance_button(self) -> QPushButton:
        self.ocr_balance_btn = QPushButton("检测余额")
        self.ocr_balance_btn.clicked.connect(self._check_ocr_balance)
        return self.ocr_balance_btn

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
    def _pair(left: QWidget, right: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(left, 1)
        layout.addWidget(right)
        return wrapper

    def load_values(self) -> None:
        self._loading_provider = True
        try:
            self._provider_models = {}
            for key, preset in PROVIDER_PRESETS.items():
                provider_config = self.config.get_ai_provider_config(key)
                self._provider_models[key] = str(
                    provider_config.get("model") or preset.default_model
                )

            provider = self.config.get_ai_provider()
            self._active_provider = provider
            index = self.provider_combo.findData(provider)
            if index >= 0:
                self.provider_combo.setCurrentIndex(index)
            self.model_edit.setText(
                self._provider_models.get(
                    provider,
                    get_provider_preset(provider).default_model,
                )
            )
        finally:
            self._loading_provider = False

        self.ocr_mode_combo.blockSignals(True)
        self.online_ocr_provider_combo.blockSignals(True)
        try:
            mode = str(self.config.get("ocr.mode", "online")).lower()
            mode_index = self.ocr_mode_combo.findData(mode)
            self.ocr_mode_combo.setCurrentIndex(
                mode_index if mode_index >= 0 else 0
            )
            online_provider = str(
                self.config.get("ocr.online_provider", "glm")
            ).lower()
            provider_index = self.online_ocr_provider_combo.findData(
                online_provider
            )
            self.online_ocr_provider_combo.setCurrentIndex(
                provider_index if provider_index >= 0 else 0
            )
            online_preset = get_online_ocr_preset(
                self.online_ocr_provider_combo.currentData()
            )
            self.online_ocr_model_edit.setText(
                str(
                    self.config.get("ocr.online_model", "")
                    or online_preset.default_model
                )
            )
            self.ocr_api_key_edit.clear()
        finally:
            self.ocr_mode_combo.blockSignals(False)
            self.online_ocr_provider_combo.blockSignals(False)
        self._refresh_ocr_controls()
        self._refresh_ocr_api_key_state()

        self.ocr_model_edit.setText(
            str(self.config.get("ocr.local_model_path", ""))
            or str(self.config.get("ocr.model_name", ""))
        )
        self.database_edit.setText(str(self.config.resolve_path("paths.database")))
        self.usage_mode_combo.setCurrentIndex(1 if self.config.get("app.usage_mode", "student") == "teacher" else 0)
        theme = str(self.config.get("app.theme", "light"))
        self.theme_combo.setCurrentText("浅色" if theme == "light" else "深色")
        self.reduce_motion_check.setChecked(
            bool(self.config.get("app.reduce_motion", False))
        )
        self._refresh_api_key_state()

    def _on_provider_changed(self, _index: int) -> None:
        if self._loading_provider:
            return
        self._remember_provider_model()
        provider = str(self.provider_combo.currentData() or "glm")
        self._active_provider = provider
        preset = get_provider_preset(provider)
        self.model_edit.setText(
            self._provider_models.get(provider, preset.default_model)
        )
        self.api_key_edit.clear()
        self._refresh_api_key_state()

    def _on_ocr_mode_changed(self, _index: int) -> None:
        self._refresh_ocr_controls()

    def _on_online_ocr_provider_changed(self, _index: int) -> None:
        if self._loading_provider:
            return
        preset = get_online_ocr_preset(
            self.online_ocr_provider_combo.currentData()
        )
        self.online_ocr_model_edit.setText(preset.default_model)
        self.ocr_api_key_edit.clear()
        self._refresh_ocr_api_key_state()

    def _refresh_ocr_controls(self) -> None:
        mode = str(self.ocr_mode_combo.currentData() or "online")
        online = mode == "online"
        local = mode == "local"
        self.online_ocr_provider_combo.setEnabled(online)
        self.online_ocr_model_edit.setEnabled(online)
        self.ocr_api_key_edit.setEnabled(online)
        self.ocr_model_edit.setEnabled(local)

    def _refresh_ocr_api_key_state(self) -> None:
        provider = str(
            self.online_ocr_provider_combo.currentData() or "glm"
        )
        preset = get_online_ocr_preset(provider)
        specific = self.config.get_ocr_api_key(
            provider=provider,
            fallback=False,
        )
        fallback = self.config.get_ocr_api_key(provider=provider)
        if specific:
            placeholder = "已单独配置，输入新值可覆盖"
        elif fallback:
            placeholder = "未单独配置，将使用评分模型 Key"
        else:
            placeholder = f"输入 {preset.label} 手写文本识别 API Key"
        self.ocr_api_key_edit.setPlaceholderText(placeholder)

    def _remember_provider_model(self) -> None:
        if self._active_provider and self.model_edit.text().strip():
            self._provider_models[self._active_provider] = (
                self.model_edit.text().strip()
            )

    def _refresh_api_key_state(self) -> None:
        provider = self._active_provider
        preset = get_provider_preset(provider)
        existing = self.config.get_api_key(provider=provider)
        self.api_key_edit.setPlaceholderText(
            "已配置，输入新值可覆盖"
            if existing
            else f"输入 {preset.label} API Key"
        )

    def _check_scoring_balance(self) -> None:
        provider = self._active_provider
        api_key = (
            self.api_key_edit.text().strip()
            or self.config.get_api_key(provider=provider)
        )
        self._run_balance_check(provider, api_key, self.balance_btn)

    def _check_ocr_balance(self) -> None:
        provider = str(
            self.online_ocr_provider_combo.currentData() or "glm"
        )
        api_key = (
            self.ocr_api_key_edit.text().strip()
            or self.config.get_ocr_api_key(provider=provider)
        )
        self._run_balance_check(provider, api_key, self.ocr_balance_btn)

    def _run_balance_check(
        self,
        provider: str,
        api_key: str | None,
        button: QPushButton,
    ) -> None:
        if not api_key:
            QMessageBox.warning(
                self,
                "未配置 API Key",
                "请先填写或保存对应 API Key。",
            )
            return
        button.setEnabled(False)
        button.setText("检测中...")
        worker = BalanceWorker(provider, api_key)
        self._balance_workers.append(worker)
        worker.signals.finished.connect(
            lambda result, w=worker, b=button, p=provider: (
                self._on_balance_result(result, w, b, p)
            )
        )
        worker.signals.error.connect(
            lambda message, w=worker, b=button, p=provider: (
                self._on_balance_error(message, w, b, p)
            )
        )
        QThreadPool.globalInstance().start(worker)

    def _on_balance_result(
        self,
        result,
        worker: BalanceWorker,
        button: QPushButton,
        provider: str,
    ) -> None:
        self._balance_workers.remove(worker)
        button.setEnabled(True)
        button.setText("检测余额")
        title = f"{provider} 余额/额度"
        if result.success:
            QMessageBox.information(self, title, result.message)
        else:
            QMessageBox.warning(self, title, result.message)

    def _on_balance_error(
        self,
        message: str,
        worker: BalanceWorker,
        button: QPushButton,
        provider: str,
    ) -> None:
        self._balance_workers.remove(worker)
        button.setEnabled(True)
        button.setText("检测余额")
        QMessageBox.warning(
            self,
            f"{provider} 余额/额度",
            message,
        )

    def _save(self) -> None:
        self._remember_provider_model()
        provider = str(self.provider_combo.currentData() or "glm")
        self._active_provider = provider
        self.config.set("ai.provider", provider)
        for key, model in self._provider_models.items():
            if model:
                self.config.set(f"ai.providers.{key}.model", model)

        self.config.set(
            "ocr.mode",
            str(self.ocr_mode_combo.currentData() or "online"),
        )
        self.config.set(
            "ocr.online_provider",
            str(self.online_ocr_provider_combo.currentData() or "glm"),
        )
        self.config.set(
            "ocr.online_model",
            self.online_ocr_model_edit.text().strip()
            or get_online_ocr_preset(
                self.online_ocr_provider_combo.currentData()
            ).default_model,
        )
        ocr_api_key = self.ocr_api_key_edit.text().strip()
        if ocr_api_key:
            self.config.set_ocr_api_key(
                ocr_api_key,
                provider=str(
                    self.online_ocr_provider_combo.currentData() or "glm"
                ),
            )

        model_value = self.ocr_model_edit.text().strip()
        if model_value:
            looks_like_path = (
                "/" in model_value
                or "\\" in model_value
                or Path(model_value).exists()
            )
            if looks_like_path:
                self.config.set("ocr.local_model_path", model_value)
                self.config.set("ocr.model_name", model_value)
            else:
                self.config.set("ocr.local_model_path", "")
                self.config.set("ocr.model_name", model_value)
        else:
            self.config.set("ocr.local_model_path", "")
            self.config.set(
                "ocr.model_name",
                "microsoft/trocr-base-handwritten",
            )
        self.config.set("paths.database", self.database_edit.text().strip())
        theme = "light" if self.theme_combo.currentText() == "浅色" else "dark"
        self.config.set("app.usage_mode", self.usage_mode_combo.currentData())
        self.config.set("app.theme", theme)
        self.config.set(
            "app.reduce_motion",
            self.reduce_motion_check.isChecked(),
        )
        api_key = self.api_key_edit.text().strip()
        if api_key:
            self.config.set_api_key(api_key, provider=provider)
        self.config.save()
        self.api_key_edit.clear()
        self.ocr_api_key_edit.clear()
        self.load_values()
        preset = get_provider_preset(provider)
        self.saved.emit()
        QMessageBox.information(
            self,
            "设置已保存",
            f"配置已保存并应用，当前 AI 服务商：{preset.label}。",
        )

    def _clear_api_key(self) -> None:
        self.config.delete_api_key(provider=self._active_provider)
        self.load_values()
        QMessageBox.information(self, "API Key 已清除", "已删除本地保存的 API Key。")

    def _clear_ocr_api_key(self) -> None:
        provider = str(
            self.online_ocr_provider_combo.currentData() or "glm"
        )
        self.config.delete_ocr_api_key(provider=provider)
        self.load_values()
        QMessageBox.information(
            self,
            "识别 API Key 已清除",
            "已删除单独保存的识别 API Key，必要时将回退使用评分模型 Key。",
        )
