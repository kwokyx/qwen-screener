"""Login / Register 端到端：注册 → 登录 → 加自选 → 重登 → 自选还在。

P1-4 验收：把整条用户旅程钉死，避免后续重构改坏其中一环。
"""
from fastapi.testclient import TestClient

from app.main import app
from app.models.stock import StockBasic


def test_full_auth_journey(db):
    db.add(StockBasic(code="600519.SH", name="贵州茅台", industry="白酒"))
    db.commit()

    with TestClient(app) as c:
        # 1. 注册
        r = c.post("/api/v1/auth/register", json={"username": "journey", "password": "abcd1234"})
        assert r.status_code == 201

        # 重复注册 → 400
        r = c.post("/api/v1/auth/register", json={"username": "journey", "password": "abcd1234"})
        assert r.status_code == 400

        # 2. 登录拿 token
        r = c.post("/api/v1/auth/login", data={"username": "journey", "password": "abcd1234"})
        assert r.status_code == 200
        t1 = r.json()["access_token"]
        assert r.json()["user"]["username"] == "journey"

        # 密码错误 → 401
        r = c.post("/api/v1/auth/login", data={"username": "journey", "password": "wrong"})
        assert r.status_code == 401

        # 3. 拉自选（空）
        h1 = {"Authorization": f"Bearer {t1}"}
        assert c.get("/api/v1/stock/me/watchlist", headers=h1).json() == []

        # 加一条
        r = c.post(
            "/api/v1/stock/me/watchlist",
            headers=h1,
            json={"code": "600519.SH",
                  "alerts": [{"id": "a1", "type": "price_gt", "threshold": 2000, "enabled": True}],
                  "ref_price": 1742.5},
        )
        assert r.status_code in (200, 201)

        # /auth/me 验身份
        r = c.get("/api/v1/auth/me", headers=h1)
        assert r.status_code == 200 and r.json()["username"] == "journey"

        # 4. "退出"：前端清 token；这里模拟为重新登录拿新 token
        r = c.post("/api/v1/auth/login", data={"username": "journey", "password": "abcd1234"})
        assert r.status_code == 200
        t2 = r.json()["access_token"]
        h2 = {"Authorization": f"Bearer {t2}"}

        # 5. 自选还在（核心验收点）
        items = c.get("/api/v1/stock/me/watchlist", headers=h2).json()
        assert len(items) == 1
        assert items[0]["code"] == "600519.SH"
        assert items[0]["ref_price"] == 1742.5
        assert len(items[0]["alerts"]) == 1

        # 6. 无 token 受保护接口 → 401
        assert c.get("/api/v1/stock/me/watchlist").status_code == 401
        assert c.get("/api/v1/auth/me").status_code == 401


def test_register_validates_password_length(db):
    """密码 < 6 位应被 schema 拒绝（不依赖前端验证）。"""
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/register", json={"username": "shortpw", "password": "abc"})
        assert r.status_code == 422


def test_register_validates_username_length(db):
    """用户名 < 3 位应被 schema 拒绝。"""
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/register", json={"username": "x", "password": "abcd1234"})
        assert r.status_code == 422
