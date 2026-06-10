from fastapi.testclient import TestClient

from app.api import market as market_api
from app.main import app


def test_market_indices_returns_real_six_when_available(db, seed_stocks, monkeypatch):
    market_api._local_market_cache.clear()
    real = {
        d["code"]: {
            "value": 3000.0 + idx,
            "change": 10.0,
            "change_pct": 0.3,
            "spark": [2900.0 + idx, 3000.0 + idx],
        }
        for idx, d in enumerate(market_api.INDEX_DEFS)
    }
    monkeypatch.setattr(market_api, "_real_indices", lambda: real)

    with TestClient(app) as client:
        response = client.get("/api/v1/market/indices")

    assert response.status_code == 200
    payload = response.json()
    assert [item["code"] for item in payload] == [
        "SH000001",
        "SH000300",
        "SH000905",
        "SH000852",
        "SZ399006",
        "SH000688",
    ]
    assert [item["name"] for item in payload] == [
        "上证指数",
        "沪深300",
        "中证500",
        "中证1000",
        "创业板指",
        "科创50",
    ]
    assert all(item["spark"] == real[item["code"]]["spark"] for item in payload)


def test_market_indices_local_fallback_uses_seed_data(db, seed_stocks, monkeypatch):
    market_api._local_market_cache.clear()
    monkeypatch.setattr(market_api, "_real_indices", lambda: {})

    with TestClient(app) as client:
        response = client.get("/api/v1/market/indices")

    assert response.status_code == 200
    payload = response.json()
    codes = {item["code"] for item in payload}
    assert {"SH000001", "SH000300", "SH000905", "SH000852", "SH000688"}.issubset(codes)
    assert all(item["spark"] for item in payload)
    assert all(item["constituents"] > 0 for item in payload if item["code"] != "SZ399006")


def test_market_industries_returns_distinct_local_industries(db, seed_stocks):
    market_api._local_market_cache.clear()

    with TestClient(app) as client:
        response = client.get("/api/v1/market/industries")

    assert response.status_code == 200
    payload = response.json()
    by_name = {item["name"]: item["count"] for item in payload}
    assert by_name["银行"] == 1
    assert by_name["白酒"] == 1
    assert by_name["半导体"] == 1
    assert all(item["name"] for item in payload)


def test_market_overview_returns_dashboard_payload(db, seed_stocks, monkeypatch):
    market_api._local_market_cache.clear()
    monkeypatch.setattr(market_api, "_real_indices", lambda: {})

    with TestClient(app) as client:
        response = client.get("/api/v1/market/overview?sector_limit=3&movers_limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"indices", "sectors", "movers", "ticker"}
    assert payload["indices"]
    assert len(payload["sectors"]) <= 3
    assert set(payload["movers"]) == {"gainers", "losers", "by_amount", "by_turnover"}
    assert payload["ticker"]["trade_date"]
