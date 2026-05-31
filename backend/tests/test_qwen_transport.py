import httpx

from app.services.qwen_client import transport


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    responses: list[_FakeResponse] = []
    calls: list[str] = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, **_kwargs):
        self.calls.append(url)
        return self.responses.pop(0)


def _mock_http(monkeypatch, responses):
    _FakeClient.responses = list(responses)
    _FakeClient.calls = []
    monkeypatch.setattr(httpx, "Client", _FakeClient)


def test_probe_health_dispatches_dashscope(monkeypatch):
    monkeypatch.setattr(transport.settings, "ai_backend", "dashscope")
    monkeypatch.setattr(
        transport,
        "_probe_dashscope_health",
        lambda timeout: {"ok": True, "latency_ms": int(timeout), "reason": None},
    )

    result = transport.probe_health(3)

    assert result == {"ok": True, "latency_ms": 3, "reason": None}


def test_openai_probe_falls_back_to_chat_completions(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    _mock_http(monkeypatch, [_FakeResponse(404), _FakeResponse(200)])

    result = transport._probe_openai_health(3)

    assert result["ok"] is True
    assert _FakeClient.calls == [
        "https://example.test/v1/responses",
        "https://example.test/v1/chat/completions",
    ]


def test_openai_probe_reports_gateway_incompatibility(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    _mock_http(
        monkeypatch,
        [
            _FakeResponse(502, "upstream failed"),
            _FakeResponse(400, "model is not supported for this account"),
        ],
    )

    result = transport._probe_openai_health(3)

    assert result["ok"] is False
    assert result["reason"] == "模型或网关不兼容: test-model"
