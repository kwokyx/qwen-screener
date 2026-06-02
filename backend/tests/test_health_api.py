from datetime import date, datetime

from fastapi.testclient import TestClient

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
