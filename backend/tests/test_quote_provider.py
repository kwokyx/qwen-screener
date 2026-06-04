import threading
import time

from app.services.providers import quote_provider


def _reset_quote_provider(monkeypatch):
    monkeypatch.setattr(quote_provider, "_quote_cache", {})
    monkeypatch.setattr(quote_provider, "_quote_recent_failures", [])
    monkeypatch.setattr(quote_provider, "_quote_circuit_disabled_until", 0.0)
    monkeypatch.setattr(quote_provider, "_quote_inflight", {})


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_realtime_quote_caches_failures(monkeypatch):
    _reset_quote_provider(monkeypatch)
    calls = []

    def fail(*_args, **_kwargs):
        calls.append("called")
        raise TimeoutError("timeout")

    monkeypatch.setattr(quote_provider.requests, "get", fail)

    assert quote_provider.fetch_realtime_quote("600036.SH") is None
    assert quote_provider.fetch_realtime_quote("600036.SH") is None

    assert calls == ["called"]


def test_realtime_quote_opens_circuit_after_repeated_failures(monkeypatch):
    _reset_quote_provider(monkeypatch)
    calls = []

    def fail(*_args, **_kwargs):
        calls.append("called")
        raise TimeoutError("timeout")

    monkeypatch.setattr(quote_provider.requests, "get", fail)

    assert quote_provider.fetch_realtime_quote("600036.SH") is None
    assert quote_provider.fetch_realtime_quote("000001.SZ") is None
    assert quote_provider.fetch_realtime_quote("688981.SH") is None
    assert quote_provider.fetch_realtime_quote("600519.SH") is None

    assert calls == ["called", "called", "called"]


def test_realtime_quote_success_resets_circuit(monkeypatch):
    _reset_quote_provider(monkeypatch)
    quote_provider._record_quote_failure()
    quote_provider._record_quote_failure()
    quote_provider._record_quote_failure()
    assert quote_provider._circuit_open() is True

    quote_provider._record_quote_success()

    assert quote_provider._circuit_open() is False


def test_realtime_quote_budget_returns_quickly_when_provider_blocks(monkeypatch):
    _reset_quote_provider(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_fetch(code, use_cache=True):
        started.set()
        release.wait(1.0)
        return {
            "code": code,
            "close": 40.0,
            "source": "tencent",
        }

    monkeypatch.setattr(quote_provider, "fetch_realtime_quote", slow_fetch)

    try:
        t0 = time.monotonic()
        result = quote_provider.fetch_realtime_quote_budgeted("600036.SH", budget=0.01)
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert result is None
        assert elapsed_ms < 120
        assert started.wait(1.0) is True
    finally:
        release.set()

    assert _wait_until(lambda: not quote_provider._quote_inflight)


def test_realtime_quote_budget_uses_cache_without_submit(monkeypatch):
    _reset_quote_provider(monkeypatch)
    payload = {
        "code": "600036.SH",
        "close": 40.0,
        "source": "tencent",
    }
    quote_provider._cache_set("600036.SH", payload, 5)

    def fail_submit(_code):
        raise AssertionError("cache hit should not submit realtime quote fetch")

    monkeypatch.setattr(quote_provider, "_submit_quote_fetch", fail_submit)

    assert quote_provider.fetch_realtime_quote_budgeted("600036.SH", budget=0.01) == payload
