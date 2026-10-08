from types import SimpleNamespace

import pytest
import requests

from ai.chat_api import get_provider_preset
from ai.model_catalog import GLM_CATALOG_URL, ModelCatalog, ModelListError, fetch_model_catalog
from tests.test_workflow_sessions import APP, CapturingPool, make_window


class Response:
    def __init__(self, payload=None, *, status=200, text=""):
        self.status_code, self.payload, self.text = status, payload, text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.mark.parametrize("provider,base", [
    ("openai", "https://api.openai.com/v1/"),
    ("deepseek", "https://api.deepseek.com/v1"),
    ("glm", "https://proxy.example/v1"),
])
def test_api_discovery_respects_endpoint_and_deduplicates(monkeypatch, provider, base):
    seen = []
    def get(url, **kwargs):
        seen.append((url, kwargs))
        return Response({"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-b"},
                                  None, {"id": True}, {"id": " "}, {"id": "bad\nvalue"}]})
    monkeypatch.setattr("ai.model_catalog.requests.get", get)
    result = fetch_model_catalog(provider, base, "test-secret")
    assert result.models == ("model-a", "model-b") and result.source == "api"
    assert seen[0][0] == base.rstrip("/") + "/models"
    assert seen[0][1]["headers"]["Authorization"] == "Bearer test-secret"
    assert seen[0][1]["allow_redirects"] is False


def test_glm_public_catalog_sends_no_key_and_scopes_purpose(monkeypatch):
    seen = []
    text = "\n".join([
        "[GLM-5.3](/cn/guide/models/text/glm-5.3)",
        "[GLM-5.3-FlashX](/cn/guide/models/vlm/glm-5.3-flash)",
        "[GLM-4.7-Flash](/cn/guide/models/free/glm-4.7-flash)",
        "[GLM-OCR](/cn/guide/models/vlm/glm-ocr)",
        "[GLM-TTS](/cn/guide/models/sound-and-video/glm-tts)",
    ])
    def get(url, **kwargs):
        seen.append((url, kwargs))
        return Response(text=text)
    monkeypatch.setattr("ai.model_catalog.requests.get", get)
    base = get_provider_preset("glm").api_base
    result = fetch_model_catalog("glm", base, "private-test-key")
    assert result.models == ("glm-4.7-flash", "glm-5.3", "glm-5.3-flashx")
    assert result.source == "public_catalog"
    assert fetch_model_catalog("glm", base, purpose="ocr").models == ("glm-ocr",)
    assert all(url == GLM_CATALOG_URL and kwargs["headers"] == {} for url, kwargs in seen)


@pytest.mark.parametrize("status", [401, 403, 404, 405, 429, 500, 302])
def test_http_errors_do_not_echo_credentials(monkeypatch, status):
    monkeypatch.setattr("ai.model_catalog.requests.get", lambda *a, **k: Response(status=status, text="test-secret"))
    with pytest.raises(ModelListError) as error:
        fetch_model_catalog("openai", "https://api.openai.com/v1", "test-secret")
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("payload", [None, {}, {"data": {}}, {"data": []}, {"data": [None, "model"]}, ValueError("secret")])
def test_invalid_or_empty_responses_have_explicit_errors(monkeypatch, payload):
    monkeypatch.setattr("ai.model_catalog.requests.get", lambda *a, **k: Response(payload))
    with pytest.raises(ModelListError):
        fetch_model_catalog("openai", "https://api.openai.com/v1", "test-key")


def test_missing_key_never_starts_request(monkeypatch):
    monkeypatch.setattr("ai.model_catalog.requests.get", lambda *a, **k: pytest.fail("unexpected request"))
    with pytest.raises(ModelListError, match="API Key"):
        fetch_model_catalog("openai", "https://api.openai.com/v1")


def test_transport_errors_are_sanitized(monkeypatch):
    def fail(*a, **k):
        raise requests.Timeout("test-secret")
    monkeypatch.setattr("ai.model_catalog.requests.get", fail)
    with pytest.raises(ModelListError) as error:
        fetch_model_catalog("openai", "https://api.openai.com/v1", "test-secret")
    assert "test-secret" not in str(error.value)


@pytest.fixture
def ui(tmp_path, monkeypatch):
    window, _ = make_window(tmp_path)
    monkeypatch.setattr(window.config, "get_ocr_api_key", lambda provider=None, fallback=True: None)
    monkeypatch.setattr(window.config, "set_api_key", lambda *a, **k: None)
    monkeypatch.setattr(window.config, "set_ocr_api_key", lambda *a, **k: None)
    pool = CapturingPool()
    monkeypatch.setattr("gui.settings_page.QThreadPool", SimpleNamespace(globalInstance=lambda: pool))
    window.show()
    window._open_settings()
    APP.processEvents()
    yield window, window.settings_page, pool
    window.close()
    APP.processEvents()


def catalog(*ids):
    return ModelCatalog(tuple(ids), "api", "https://example.test/models")


def test_editable_selection_preserves_in_flight_edits_and_saves(ui):
    w, page, pool = ui
    page.api_key_edit.setText("unsaved-test-key")
    page.models_btn.click()
    page._fetch_models("scoring")
    assert len(pool.workers) == 1
    assert pool.workers[0].api_key == "unsaved-test-key"
    page.model_edit.setText("custom-during-fetch")
    pool.workers[0].signals.finished.emit(catalog("model-one", "model-two"))
    assert page.model_edit.text() == "custom-during-fetch"
    assert page.model_combo.findText("model-two") >= 0
    page.model_combo.setCurrentIndex(page.model_combo.findText("model-two"))
    page._save()
    assert w.config.get_ai_provider_config("glm")["model"] == "model-two"
    assert page.model_combo.findText("model-one") >= 0
    assert "unsaved-test-key" not in w.config.user_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["provider", "key", "leave", "base"])
def test_obsolete_fetch_does_not_replace_current_choices(ui, change):
    w, page, pool = ui
    page.models_btn.click()
    worker = pool.workers[0]
    if change == "provider":
        page.provider_combo.setCurrentIndex(page.provider_combo.findData("openai"))
        page.provider_combo.setCurrentIndex(page.provider_combo.findData("glm"))
    elif change == "key":
        page.api_key_edit.setText("changed-test-key")
    elif change == "leave":
        w._navigate(0)
    else:
        w.config.set("ai.providers.glm.api_base", "https://other.example/v1")
    value = page.model_edit.text()
    worker.signals.finished.emit(catalog("obsolete-model"))
    assert page.model_edit.text() == value
    assert page.model_combo.findText("obsolete-model") == -1
    assert page.models_btn.isEnabled()


def test_refresh_keeps_current_model_selected_in_popup(ui):
    w, page, pool = ui
    current = page.model_edit.text()
    page.models_btn.click()
    pool.workers[0].signals.finished.emit(catalog("aaa-first-model", current))
    assert page.model_combo.currentIndex() == page.model_combo.findText(current)
    assert page.model_combo.currentText() == current


def test_ocr_fetch_uses_unsaved_scoring_key_and_respects_mode(ui):
    w, page, pool = ui
    page.ocr_mode_combo.setCurrentIndex(page.ocr_mode_combo.findData("online"))
    page.api_key_edit.setText("unsaved-scoring-key")
    page.ocr_models_btn.click()
    assert pool.workers[0].api_key == "unsaved-scoring-key"
    assert pool.workers[0].purpose == "ocr"
    page.ocr_mode_combo.setCurrentIndex(page.ocr_mode_combo.findData("manual"))
    pool.workers[0].signals.finished.emit(catalog("obsolete-ocr"))
    assert not page.ocr_models_btn.isEnabled()
    assert page.online_ocr_model_combo.findText("obsolete-ocr") == -1


def test_fetch_failure_keeps_manual_model_and_allows_retry(ui):
    w, page, pool = ui
    page.model_edit.setText("my-custom-model")
    page.models_btn.click()
    pool.workers[0].signals.error.emit("请求失败，可重试。")
    assert page.model_edit.text() == "my-custom-model"
    assert page.models_btn.isEnabled()
    assert "重试" in page.models_status.text()
    page.models_btn.click()
    assert len(pool.workers) == 2
