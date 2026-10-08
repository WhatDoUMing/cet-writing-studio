import json

import pytest

from ai.chat_api import (
    ChatAPIError,
    ChatCompletionClient,
    validate_report_scores,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def report_json(score=12, content="", language="", struct=""):
    from tests.test_cet_contract import valid_report
    try:
        score=int(score)
    except (ValueError,TypeError):
        pass
    return json.dumps(valid_report(score))


def test_openai_client_uses_chat_completions(monkeypatch) -> None:
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
                            "content": report_json()
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient(
        "openai",
        {"model": "gpt-test", "temperature": 0.3},
        api_key="openai-key",
    )
    report = client.grade_essay(
        essay_type="CET-4",
        max_score="15",
        question="题目",
        student_text="A short essay.",
    )

    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    payload = captured["json"]
    assert payload["model"] == "gpt-test"
    assert payload["max_completion_tokens"] == 4096
    assert "temperature" not in payload
    assert "top_k" not in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert report["score"] == 12


def test_deepseek_client_uses_chat_completions(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            200,
            {
                "choices": [
                    {"message": {"content": report_json("15", "5", "5", "5")}}
                ]
            },
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient(
        "deepseek",
        {"model": "deepseek-test"},
        api_key="deepseek-key",
    )
    client.grade_essay(
        essay_type="CET-6",
        max_score="15",
        question="题目",
        student_text="A short essay.",
    )

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    payload = captured["json"]
    assert payload["model"] == "deepseek-test"
    assert payload["max_tokens"] == 4096
    assert payload["temperature"] == 0.7
    assert "top_k" not in payload


def test_missing_provider_key_has_clear_error() -> None:
    client = ChatCompletionClient("deepseek")
    with pytest.raises(ChatAPIError, match="DeepSeek"):
        client.chat([{"role": "user", "content": "hello"}])


def test_glm_retries_without_top_k(monkeypatch) -> None:
    payloads: list[dict] = []
    responses = [
        FakeResponse(400, {"error": {"message": "invalid top_k"}}),
        FakeResponse(
            200,
            {
                "choices": [
                    {"message": {"content": report_json("12", "7", "7", "5")}}
                ]
            },
        ),
    ]

    def fake_post(_url: str, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("glm", api_key="glm-key")
    result = client.grade_essay(
        essay_type="CET-4",
        max_score="15",
        question="题目",
        student_text="A short essay.",
    )

    assert result["score"] == 12
    assert payloads[0]["top_k"] == 10
    assert "top_k" not in payloads[1]
    assert payloads[1]["top_p"] == 0.7


def test_empty_content_retries_without_json_mode(monkeypatch) -> None:
    payloads: list[dict] = []
    responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {"content": ""},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
        FakeResponse(
            200,
            {
                "choices": [
                    {"message": {"content": report_json("10", "6", "6", "5")}}
                ]
            },
        ),
    ]

    def fake_post(_url: str, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("openai", api_key="openai-key")
    result = client.grade_essay(
        essay_type="CET-4",
        max_score="15",
        question="题目",
        student_text="A short essay.",
    )

    assert result["score"] == 10
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]


def test_reasoning_content_is_used_as_fallback(monkeypatch) -> None:
    def fake_post(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": '{"score":"16"}',
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("deepseek", api_key="deepseek-key")
    content = client.chat([{"role": "user", "content": "hello"}])

    assert content == '{"score":"16"}'


def test_truncated_json_retries_with_larger_output_limit(monkeypatch) -> None:
    payloads: list[dict] = []
    responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"score":"12","advantages":["good"'
                        },
                        "finish_reason": "length",
                    }
                ]
            },
        ),
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                report_json(12)
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]

    def fake_post(_url: str, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient(
        "deepseek",
        {"max_tokens": 4096},
        api_key="deepseek-key",
    )
    report = client.grade_essay(
        essay_type="CET-4",
        max_score="15",
        question="题目",
        student_text="A short essay.",
    )

    assert report["score"] == 12
    assert len(payloads) == 2
    assert payloads[0]["max_tokens"] == 4096
    assert payloads[1]["max_tokens"] == 8192
    assert "截断" in payloads[1]["messages"][-1]["content"]


def test_question_summary_is_short_and_plain(monkeypatch) -> None:
    def fake_post(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "这是一段明显超过三十个字符限制的题目概括内容，"
                                "用于验证系统会拒绝过长摘要。"
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("deepseek", api_key="deepseek-key")
    summary = client.summarize_question("测试作文题目")

    assert len(summary) <= 30
    assert "。" not in summary


def test_question_summary_preserves_comparison_style(monkeypatch) -> None:
    expected = "戏剧节剧本：现代化改编vs忠于原著"

    def fake_post(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": expected}}]},
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("deepseek", api_key="deepseek-key")
    summary = client.summarize_question(
        "口语课上外教组织同学们讨论、为学校戏剧节准备节目时，"
        "你更倾向于对经典剧本进行现代化改编还是忠于原著？"
        "请你发言，内容包括观点和理由。"
    )
    assert summary == expected


def test_invalid_scores_retry_once_and_can_recover(monkeypatch) -> None:
    payloads: list[dict] = []
    responses = [
        FakeResponse(
            200,
            {"choices": [{"message": {"content": report_json("30", "10", "10", "10")}}]},
        ),
        FakeResponse(
            200,
            {"choices": [{"message": {"content": report_json("12", "8", "7.5", "5")}}]},
        ),
    ]

    def fake_post(_url: str, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("deepseek", api_key="test-key")
    report = client.grade_essay(
        essay_type="CET-4",
        max_score="15",
        question="题目",
        student_text="Essay",
    )
    assert report["score"] == 12
    assert len(payloads) == 2
    assert "重新输出完整 JSON" in payloads[1]["messages"][-1]["content"]


def test_invalid_scores_retry_once_then_raise(monkeypatch) -> None:
    calls = 0

    def fake_post(_url: str, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": report_json("NaN", "8", "7", "5")}}]},
        )

    monkeypatch.setattr("ai.chat_api.requests.post", fake_post)
    client = ChatCompletionClient("openai", api_key="test-key")
    with pytest.raises(ChatAPIError, match="修正重试后仍无效"):
        client.grade_essay(
            essay_type="CET-4",
            max_score="15",
            question="题目",
            student_text="Essay",
        )
    assert calls == 2
