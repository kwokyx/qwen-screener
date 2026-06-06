"""Watchlist 后端同步：POST 是 upsert，能写入 alerts / ref_price 并被 GET 读出。"""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.stock import StockBasic
from tests.auth_helpers import login_form, register_json


def _register_and_login(client: TestClient, u="wl_user", p="abcd1234"):
    client.post("/api/v1/auth/register", json=register_json(client, u, p))
    r = client.post("/api/v1/auth/login", data=login_form(client, u, p))
    assert r.status_code == 200
    return r.json()["access_token"]


def test_watchlist_upsert_persists_alerts(db):
    db.add(StockBasic(code="600519.SH", name="贵州茅台", industry="白酒"))
    db.commit()

    with TestClient(app) as c:
        token = _register_and_login(c, u="wl_user1")
        h = {"Authorization": f"Bearer {token}"}

        alerts = [{"id": "a1", "type": "price_gt", "threshold": 2000, "enabled": True, "lastTriggered": None}]
        r = c.post(
            "/api/v1/stock/me/watchlist",
            headers=h,
            json={"code": "600519.SH", "alerts": alerts, "ref_price": 1742.5},
        )
        assert r.status_code in (200, 201)
        body = r.json()
        assert body["alerts"] == alerts
        assert body["ref_price"] == 1742.5
        assert body["created_at"]

        # 第二次 POST 同 code → 更新 alerts，不是创建新行
        alerts2 = alerts + [{"id": "a2", "type": "price_lt", "threshold": 1500, "enabled": True, "lastTriggered": None}]
        r2 = c.post(
            "/api/v1/stock/me/watchlist",
            headers=h,
            json={"code": "600519.SH", "alerts": alerts2},
        )
        assert r2.status_code in (200, 201)
        assert r2.json()["alerts"] == alerts2
        # ref_price 不传时不要清掉之前的值
        assert r2.json()["ref_price"] == 1742.5

        # GET 拉回来
        r3 = c.get("/api/v1/stock/me/watchlist", headers=h)
        assert r3.status_code == 200
        items = r3.json()
        assert len(items) == 1
        assert items[0]["alerts"] == alerts2
        assert items[0]["ref_price"] == 1742.5
        assert items[0]["created_at"] == body["created_at"]


def test_watchlist_delete(db):
    db.add(StockBasic(code="600519.SH", name="贵州茅台", industry="白酒"))
    db.commit()

    with TestClient(app) as c:
        token = _register_and_login(c, u="wl_user2")
        h = {"Authorization": f"Bearer {token}"}

        c.post("/api/v1/stock/me/watchlist", headers=h, json={"code": "600519.SH"})
        r = c.delete("/api/v1/stock/me/watchlist/600519.SH", headers=h)
        assert r.status_code == 204

        r2 = c.get("/api/v1/stock/me/watchlist", headers=h)
        assert r2.json() == []
