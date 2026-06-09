"""stock detail 接口：change_pct 计算（有/无前日数据）。"""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api import stock as stock_api
from app.main import app
from app.models.stock import StockBasic, StockDaily


def test_change_pct_with_prev_close(db):
    """有前一交易日数据 → change_pct 正确计算。"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    db.add(StockBasic(code="123456.SH", name="测试股", industry="测试"))
    db.add(StockDaily(code="123456.SH", trade_date=yesterday, close=100.0))
    db.add(StockDaily(code="123456.SH", trade_date=today,     close=110.0))
    db.commit()

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/123456.SH")
        assert r.status_code == 200
        d = r.json()
        assert d["latest"]["close"] == 110.0
        assert d["prev_close"] == 100.0
        assert abs(d["change_pct"] - 10.0) < 0.001  # +10%


def test_change_pct_first_day(db):
    """只有 1 行数据 → prev_close 和 change_pct 都为 None，不抛。"""
    db.add(StockBasic(code="999999.SH", name="新股", industry="测试"))
    db.add(StockDaily(code="999999.SH", trade_date=date.today(), close=50.0))
    db.commit()

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/999999.SH")
        assert r.status_code == 200
        d = r.json()
        assert d["prev_close"] is None
        assert d["change_pct"] is None


def test_stock_not_found(db):
    """不存在的代码 → 404。"""
    with TestClient(app) as c:
        r = c.get("/api/v1/stock/000000.XX")
        assert r.status_code == 404


def test_quote_falls_back_to_local_daily_when_live_unavailable(db, monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)
    db.add(StockBasic(code="123456.SH", name="测试股", industry="测试"))
    db.add(StockDaily(code="123456.SH", trade_date=yesterday, close=100.0))
    db.add(StockDaily(
        code="123456.SH",
        trade_date=today,
        open=101.0,
        high=111.0,
        low=99.0,
        close=110.0,
        volume=12345,
        turnover=2.3,
        pe=8.5,
        pb=0.9,
        market_cap=300,
    ))
    db.commit()

    from app.services.providers import quote_provider

    monkeypatch.setattr(quote_provider, "fetch_realtime_quote_budgeted", lambda code: None)

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/123456.SH/quote")

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "local"
    assert body["close"] == 110.0
    assert body["prev_close"] == 100.0
    assert abs(body["change_pct"] - 10.0) < 0.001


def test_quote_live_response_uses_local_latest_for_dividend_without_500(db, monkeypatch):
    today = date.today()
    db.add(StockBasic(code="123456.SH", name="测试股", industry="测试"))
    db.add(StockDaily(
        code="123456.SH",
        trade_date=today,
        close=110.0,
        volume=12345,
    ))
    db.commit()

    from app.services.providers import quote_provider

    monkeypatch.setattr(quote_provider, "fetch_realtime_quote_budgeted", lambda code: {
        "code": code,
        "name": None,
        "close": 111.0,
        "source": "tencent",
    })

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/123456.SH/quote")

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "tencent"
    assert body["name"] == "测试股"
    assert body["close"] == 111.0


def test_kline_returns_chronological_daily_rows(db):
    """日 K 接口对外返回旧到新，避免前端小图趋势反向。"""
    db.add(StockBasic(code="123456.SH", name="测试股", industry="测试"))
    days = [
        date(2026, 5, 26),
        date(2026, 5, 27),
        date(2026, 5, 28),
        date(2026, 5, 29),
    ]
    for idx, day in enumerate(days, start=1):
        db.add(StockDaily(
            code="123456.SH",
            trade_date=day,
            open=idx,
            high=idx + 0.5,
            low=idx - 0.5,
            close=idx,
            volume=idx * 1000,
        ))
    db.commit()

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/123456.SH/kline?days=3&frequency=d")

    assert r.status_code == 200
    payload = r.json()
    assert [row["trade_date"] for row in payload] == [
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
    ]
    assert [row["close"] for row in payload] == [2.0, 3.0, 4.0]


def test_kline_returns_partial_local_rows_while_backfill_runs(db, monkeypatch):
    """已有快照时先返回本地数据，不让详情页同步等待免费数据源补线。"""
    queued = []
    db.add(StockBasic(code="123456.SH", name="测试股", industry="测试"))
    db.add(StockDaily(
        code="123456.SH",
        trade_date=date(2026, 5, 29),
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=1000,
    ))
    db.commit()
    monkeypatch.setattr(stock_api, "_queue_daily_backfill", lambda code, days, provider: queued.append((code, days, provider)))

    with TestClient(app) as c:
        r = c.get("/api/v1/stock/123456.SH/kline?days=120&frequency=d")

    assert r.status_code == 200
    assert [row["trade_date"] for row in r.json()] == ["2026-05-29"]
    assert queued == [("123456.SH", 120, "baostock")]


def test_intraday_timeout_opens_short_circuit(seed_stocks, monkeypatch):
    """分钟线超时后短时间内直接降级，避免用户反复等待。"""
    calls = []
    monkeypatch.setattr(stock_api, "_baostock_intraday_disabled_until", 0.0)
    monkeypatch.setattr(stock_api, "_intraday_cache", {})

    def fail(*_args, **_kwargs):
        calls.append("called")
        raise TimeoutError("baostock 分钟线查询超时")

    monkeypatch.setattr(stock_api, "_fetch_intraday_with_timeout", fail)

    with TestClient(app) as c:
        first = c.get("/api/v1/stock/600519.SH/intraday?frequency=5&days=1")
        second = c.get("/api/v1/stock/600519.SH/intraday?frequency=15&days=1")

    assert first.status_code == 503
    assert "查询超时" in first.json()["detail"]
    assert second.status_code == 503
    assert "已临时停用拉取" in second.json()["detail"]
    assert calls == ["called"]
