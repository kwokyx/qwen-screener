from datetime import date, datetime

from app.api import health
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
