from app.services.providers import quote_provider


def _reset_quote_provider(monkeypatch):
    monkeypatch.setattr(quote_provider, "_quote_cache", {})
    monkeypatch.setattr(quote_provider, "_quote_recent_failures", [])
    monkeypatch.setattr(quote_provider, "_quote_circuit_disabled_until", 0.0)


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
