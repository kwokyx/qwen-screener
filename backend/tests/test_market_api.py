from fastapi.testclient import TestClient

from app.api import market as market_api
from app.main import app


def test_market_indices_local_fallback_uses_seed_data(db, seed_stocks):
    market_api._local_market_cache.clear()

    with TestClient(app) as client:
        response = client.get("/api/v1/market/indices")

    assert response.status_code == 200
    payload = response.json()
    codes = {item["code"] for item in payload}
    assert {"SH000001", "SZ399001", "SH000688"}.issubset(codes)
    assert all(item["spark"] for item in payload)
    assert all(item["constituents"] > 0 for item in payload)

