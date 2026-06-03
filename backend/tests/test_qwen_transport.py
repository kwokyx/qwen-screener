import json
import time
from types import SimpleNamespace

import httpx

from app.services.qwen_client import transport


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text or "{}")


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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **_kwargs):
        self.calls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _mock_http(monkeypatch, responses, *, reset_breaker=True):
    _FakeClient.responses = list(responses)
    _FakeClient.calls = []
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(transport.settings, "openai_responses_enabled", True)
    if reset_breaker:
        monkeypatch.setattr(transport, "_responses_unavailable_until", 0.0)


def _reset_health_cache(monkeypatch):
    monkeypatch.setattr(transport, "_health_cache", None)
    monkeypatch.setattr(transport, "_last_health_ok", None)


def test_probe_health_dispatches_dashscope(monkeypatch):
    _reset_health_cache(monkeypatch)
    monkeypatch.setattr(transport.settings, "ai_backend", "dashscope")
    monkeypatch.setattr(transport.settings, "dashscope_api_key", "dash-key")
    monkeypatch.setattr(
        transport,
        "_probe_dashscope_health",
        lambda timeout: {"ok": True, "latency_ms": int(timeout), "reason": None},
    )

    result = transport.probe_health(3)

    assert result == {
        "ok": True,
        "latency_ms": 3,
        "reason": None,
        "backend": "dashscope",
        "model": "qwen-plus",
        "configured": True,
        "fallback": False,
        "mode": "ai_agent",
    }


def test_probe_health_reuses_short_cache(monkeypatch):
    _reset_health_cache(monkeypatch)
    monkeypatch.setattr(transport.settings, "ai_backend", "openai")
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_model", "gpt-5.4-mini")
    calls = []
    monkeypatch.setattr(
        transport,
        "_probe_openai_health",
        lambda timeout: calls.append(timeout) or {"ok": True, "latency_ms": 123, "reason": None},
    )

    first = transport.probe_health(3)
    second = transport.probe_health(3)

    assert first == second == {
        "ok": True,
        "latency_ms": 123,
        "reason": None,
        "backend": "openai",
        "model": "gpt-5.4-mini",
        "configured": True,
        "fallback": False,
        "mode": "ai_agent",
    }
    assert calls == [3]


def test_probe_health_keeps_recent_success_on_transient_failure(monkeypatch):
    _reset_health_cache(monkeypatch)
    monkeypatch.setattr(transport.settings, "ai_backend", "openai")
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    results = [
        {"ok": True, "latency_ms": 123, "reason": None},
        {"ok": False, "latency_ms": None, "reason": "上游网络不可达"},
    ]
    monkeypatch.setattr(transport, "_probe_openai_health", lambda _timeout: results.pop(0))

    assert transport.probe_health(3)["ok"] is True
    monkeypatch.setattr(transport, "_health_cache", None)
    degraded = transport.probe_health(3)

    assert degraded["ok"] is True
    assert degraded["stale"] is True
    assert degraded["mode"] == "ai_agent"


def test_probe_health_retries_initial_transient_failure(monkeypatch):
    _reset_health_cache(monkeypatch)
    monkeypatch.setattr(transport.settings, "ai_backend", "openai")
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.time, "sleep", lambda _seconds: None)
    results = [
        {"ok": False, "latency_ms": None, "reason": "上游网络不可达"},
        {"ok": True, "latency_ms": 456, "reason": None},
    ]
    monkeypatch.setattr(transport, "_probe_openai_health", lambda _timeout: results.pop(0))

    result = transport.probe_health(3)

    assert result["ok"] is True
    assert result["latency_ms"] == 456
    assert result["reason"] is None
    assert result["mode"] == "ai_agent"
    assert results == []


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


def test_openai_probe_falls_back_when_responses_times_out(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    _mock_http(monkeypatch, [httpx.ReadTimeout("responses timed out"), _FakeResponse(200)])

    result = transport._probe_openai_health(3)

    assert result["ok"] is True
    assert _FakeClient.calls == [
        "https://example.test/v1/responses",
        "https://example.test/v1/chat/completions",
    ]


def test_openai_probe_skips_responses_during_breaker(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    monkeypatch.setattr(transport.settings, "openai_responses_enabled", True)
    monkeypatch.setattr(transport, "_responses_unavailable_until", time.monotonic() + 60)
    _mock_http(monkeypatch, [_FakeResponse(200)], reset_breaker=False)

    result = transport._probe_openai_health(3)

    assert result["ok"] is True
    assert _FakeClient.calls == ["https://example.test/v1/chat/completions"]


def test_openai_probe_skips_responses_when_disabled(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    _mock_http(monkeypatch, [_FakeResponse(200)])
    monkeypatch.setattr(transport.settings, "openai_responses_enabled", False)

    result = transport._probe_openai_health(3)

    assert result["ok"] is True
    assert _FakeClient.calls == ["https://example.test/v1/chat/completions"]


def test_openai_call_skips_responses_during_breaker(monkeypatch):
    class _FakeOpenAI:
        responses = SimpleNamespace(create=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should skip")))
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                ),
            ),
        )

    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    monkeypatch.setattr(transport.settings, "openai_responses_enabled", True)
    monkeypatch.setattr(transport, "_responses_unavailable_until", time.monotonic() + 60)
    monkeypatch.setattr(transport, "openai_client", lambda: _FakeOpenAI())

    assert transport._openai_call_once("hello") == "ok"


def test_openai_call_skips_responses_when_disabled(monkeypatch):
    class _FakeOpenAI:
        responses = SimpleNamespace(create=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should skip")))
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                ),
            ),
        )

    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    monkeypatch.setattr(transport.settings, "openai_responses_enabled", False)
    monkeypatch.setattr(transport, "_responses_unavailable_until", 0.0)
    monkeypatch.setattr(transport, "openai_client", lambda: _FakeOpenAI())

    assert transport._openai_call_once("hello") == "ok"


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


def test_openai_probe_reports_inference_unavailable_with_model_catalog(monkeypatch):
    monkeypatch.setattr(transport.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transport.settings, "openai_base_url", "https://example.test")
    monkeypatch.setattr(transport.settings, "openai_model", "test-model")
    _mock_http(
        monkeypatch,
        [
            _FakeResponse(503, '{"error":{"message":"Service temporarily unavailable"}}'),
            _FakeResponse(503, '{"error":{"message":"Service temporarily unavailable"}}'),
            _FakeResponse(200, '{"data":[{"id":"test-model"}]}'),
        ],
    )

    result = transport._probe_openai_health(3)

    assert result["ok"] is False
    assert result["reason"] == "上游网关推理端不可用: HTTP 503（模型列表正常）"
    assert result["backend"] == "openai"
    assert result["model"] == "test-model"
    assert result["stage"] == "inference"
    assert result["responses_status"] == 503
    assert result["chat_status"] == 503
    assert result["models_status"] == 200
    assert result["model_listed"] is True
    assert _FakeClient.calls == [
        "https://example.test/v1/responses",
        "https://example.test/v1/chat/completions",
        "https://example.test/v1/models",
    ]
