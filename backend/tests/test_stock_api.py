"""stock detail 接口：change_pct 计算（有/无前日数据）。"""
from datetime import date, timedelta

from fastapi.testclient import TestClient

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
