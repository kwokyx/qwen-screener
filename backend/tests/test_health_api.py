from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import health
from app.main import app
from app.models.stock import StockBasic, StockDaily


def test_latest_expected_weekday_rolls_weekend_back_to_friday():
    assert health._latest_expected_weekday(date(2026, 5, 29)) == date(2026, 5, 29)
    assert health._latest_expected_weekday(date(2026, 5, 30)) == date(2026, 5, 29)
    assert health._latest_expected_weekday(date(2026, 5, 31)) == date(2026, 5, 29)


def test_latest_expected_weekday_uses_previous_close_before_market_sync():
    assert health._latest_expected_weekday(datetime(2026, 6, 1, 9, 30)) == date(2026, 5, 29)
    assert health._latest_expected_weekday(datetime(2026, 6, 1, 16, 0)) == date(2026, 6, 1)


def test_data_health_treats_friday_close_as_fresh_on_sunday(db, monkeypatch):
    monkeypatch.setattr(health, "_latest_expected_weekday", lambda: date(2026, 5, 29))
    db.add(StockBasic(code="600519.SH", name="贵州茅台"))
    db.add(StockDaily(code="600519.SH", trade_date=date(2026, 5, 29), close=1326))
    db.commit()

    result = health.data_health(db)

    assert result["fresh"] is True
    assert result["expected_trade_date"] == "2026-05-29"
    assert result["latest_trade_date"] == "2026-05-29"
    assert result["freshness"]["reason_code"] == "fresh"
    assert result["freshness"]["recommended_jobs"] == []


def test_data_health_explains_stale_market_snapshot(db, monkeypatch):
    monkeypatch.setattr(health, "_latest_expected_weekday", lambda: date(2026, 6, 3))
    db.add(StockBasic(code="600036.SH", name="招商银行"))
    db.add(StockDaily(code="600036.SH", trade_date=date(2026, 6, 2), close=40))
    db.commit()

    result = health.data_health(db)

    assert result["fresh"] is False
    assert result["latest_trade_date"] == "2026-06-02"
    assert result["freshness"]["reason_code"] == "stale"
    assert result["freshness"]["lag_days"] == 1
    assert "daily_market" in result["freshness"]["recommended_jobs"]


def test_data_health_distinguishes_sparse_newer_rows_from_market_freshness(db, monkeypatch):
    monkeypatch.setattr(health, "_latest_expected_weekday", lambda: date(2026, 6, 3))
    for idx in range(120):
        code = f"60{idx:04d}.SH"
        db.add(StockBasic(code=code, name=f"股票{idx}"))
        db.add(StockDaily(code=code, trade_date=date(2026, 6, 2), close=10))
    db.add(StockDaily(code="600000.SH", trade_date=date(2026, 6, 3), close=11))
    db.commit()

    result = health.data_health(db)

    assert result["fresh"] is False
    assert result["latest_trade_date"] == "2026-06-02"
    assert result["newest_trade_date"] == "2026-06-03"
    assert result["counts"]["market_coverage_threshold"] == 100
    assert result["freshness"]["reason_code"] == "partial_newer_data"
    assert result["freshness"]["has_sparse_newer_data"] is True
    assert result["freshness"]["latest_coverage_rows"] == 120


def test_data_health_reports_stuck_sync_job(db):
    health.scheduler._ensure_meta_table()
    old = datetime.utcnow() - timedelta(minutes=90)
    with health.scheduler.engine.begin() as conn:
        conn.execute(text("DELETE FROM sync_meta"))
        conn.execute(text(
            "INSERT INTO sync_meta (name, last_run_at, status, duration_ms, detail) "
            "VALUES (:n, :t, :s, :d, :x)"
        ), {
            "n": "daily_market",
            "t": old,
            "s": "running",
            "d": 0,
            "x": "任务执行中",
        })

    result = health.data_health(db)

    assert result["sync_has_issue"] is True
    assert result["sync_meta"]["daily_market"]["display_status"] == "stuck"
    assert result["sync_meta"]["daily_market"]["stuck"] is True
    assert result["sync_warnings"][0]["label"] == "日线行情"
    with health.scheduler.engine.begin() as conn:
        conn.execute(text("DELETE FROM sync_meta"))


def test_data_health_is_public_but_manual_sync_requires_login(db, monkeypatch):
    monkeypatch.setattr(health.scheduler, "run_async", lambda job: {"status": "queued"})

    with TestClient(app) as c:
        assert c.get("/api/v1/health/data").status_code == 200
        assert c.post("/api/v1/health/sync/daily_market").status_code == 401

        r = c.post("/api/v1/auth/register", json={"username": "syncer", "password": "abcd1234"})
        assert r.status_code == 201
        r = c.post("/api/v1/auth/login", data={"username": "syncer", "password": "abcd1234"})
        assert r.status_code == 200
        token = r.json()["access_token"]

        r = c.post(
            "/api/v1/health/sync/daily_market",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["queued"] is True


def test_ai_health_reports_runtime_status_without_secret(monkeypatch):
    monkeypatch.setattr(health.settings, "ai_backend", "openai")
    monkeypatch.setattr(health.settings, "openai_model", "model-test")
    monkeypatch.setattr(health.settings, "openai_api_key", "secret-key")
    monkeypatch.setattr(
        health.qwen_client,
        "probe_health",
        lambda timeout=6.0: {
            "ok": False,
            "latency_ms": 321,
            "reason": "上游网关推理端不可用: HTTP 503",
            "backend": "openai",
            "model": "model-test",
            "configured": True,
            "fallback": True,
            "mode": "local_fallback",
        },
    )

    with TestClient(app) as c:
        r = c.get("/api/v1/health/ai")

    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["backend"] == "openai"
    assert body["model"] == "model-test"
    assert body["mode"] == "local_fallback"
    assert body["fallback"] is True
    assert "secret-key" not in r.text
    assert "api_key" not in r.text.lower()
