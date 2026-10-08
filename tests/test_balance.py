from ai.balance import query_balance


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_deepseek_balance(monkeypatch) -> None:
    def fake_get(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "12.34",
                        "granted_balance": "2.00",
                        "topped_up_balance": "10.34",
                    }
                ],
            },
        )

    monkeypatch.setattr("ai.balance.requests.get", fake_get)
    result = query_balance("deepseek", "key")

    assert result.success is True
    assert "12.34" in result.message


def test_zhipu_quota(monkeypatch) -> None:
    def fake_get(_url: str, **_kwargs):
        return FakeResponse(
            200,
            {
                "success": True,
                "data": {
                    "level": "pro",
                    "limits": [
                        {"type": "TOKENS_LIMIT", "percentage": 25.0}
                    ],
                },
            },
        )

    monkeypatch.setattr("ai.balance.requests.get", fake_get)
    result = query_balance("glm", "key")

    assert result.success is True
    assert "剩余 75.0%" in result.message
    assert "pro" in result.message


def test_openai_balance_is_explicitly_unsupported() -> None:
    result = query_balance("openai", "key")
    assert result.success is False
    assert "不提供公开的余额查询接口" in result.message
