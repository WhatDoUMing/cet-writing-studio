from pathlib import Path

import pytest
from PIL import Image

from ocr.online_engine import OnlineOCREngine, OnlineOCRError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_deepseek_vision_ocr_sends_image(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "essay.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    captured: dict = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "First line.\nSecond line."
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("ocr.online_engine.requests.post", fake_post)
    engine = OnlineOCREngine(
        {
            "online_provider": "deepseek",
            "online_model": "deepseek-v4-flash",
        },
        api_key="deepseek-key",
    )
    text = engine.recognize(image_path)

    assert text == "First line.\nSecond line."
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    payload = captured["json"]
    assert payload["model"] == "deepseek-v4-flash"
    image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")


def test_glm_ocr_uses_layout_parsing_endpoint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "essay.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    captured: dict = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(200, {"md_results": "Recognized essay text."})

    monkeypatch.setattr("ocr.online_engine.requests.post", fake_post)
    engine = OnlineOCREngine(
        {
            "online_provider": "glm",
            "online_model": "glm-ocr",
        },
        api_key="glm-key",
    )

    assert engine.recognize(image_path) == "Recognized essay text."
    assert captured["url"].endswith("/api/paas/v4/layout_parsing")
    assert captured["json"]["model"] == "glm-ocr"
    assert captured["json"]["file"].startswith("data:image/jpeg;base64,")


def test_glm_ocr_retries_with_raw_base64(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "essay.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    payloads: list[dict] = []
    responses = [
        FakeResponse(400, {"message": "OCR format error"}),
        FakeResponse(200, {"md_results": "Recognized text."}),
    ]

    def fake_post(_url: str, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr("ocr.online_engine.requests.post", fake_post)
    engine = OnlineOCREngine(
        {"online_provider": "glm", "online_model": "glm-ocr"},
        api_key="glm-key",
    )

    assert engine.recognize(image_path) == "Recognized text."
    assert payloads[0]["file"].startswith("data:image/jpeg;base64,")
    assert not payloads[1]["file"].startswith("data:")


def test_online_ocr_empty_content_is_reported(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "essay.png"
    Image.new("RGB", (100, 50), "white").save(image_path)

    def fake_post(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": ""}}]},
        )

    monkeypatch.setattr("ocr.online_engine.requests.post", fake_post)
    engine = OnlineOCREngine(
        {"online_provider": "deepseek"},
        api_key="deepseek-key",
    )
    with pytest.raises(OnlineOCRError, match="空内容"):
        engine.recognize(image_path)


def test_openai_vision_uses_completion_token_field(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "essay.png"
    Image.new("RGB", (100, 50), "white").save(image_path)
    captured: dict = {}

    def fake_post(_url: str, **kwargs):
        captured.update(kwargs)
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "Text"}}]},
        )

    monkeypatch.setattr("ocr.online_engine.requests.post", fake_post)
    engine = OnlineOCREngine(
        {"online_provider": "openai"},
        api_key="openai-key",
    )
    assert engine.recognize(image_path) == "Text"
    assert captured["json"]["max_completion_tokens"] == 4096
    assert "temperature" not in captured["json"]
