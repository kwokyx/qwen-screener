"""通知中心持久化：CRUD + 已读 + 用户隔离。"""
from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient, u: str, p: str = "abcd1234"):
    client.post("/api/v1/auth/register", json={"username": u, "password": p})
    r = client.post("/api/v1/auth/login", data={"username": u, "password": p})
    return r.json()["access_token"]


def test_notification_crud_flow(db):
    with TestClient(app) as c:
        token = _login(c, "notif_u1")
        h = {"Authorization": f"Bearer {token}"}

        # 空起步
        assert c.get("/api/v1/notifications", headers=h).json() == []

        # 创建
        payload = {
            "kind": "alert",
            "tone": "up",
            "stock_code": "600519.SH",
            "title": "涨幅 ≥5%",
            "desc": "现价 1900 较加入价 1742.5 上涨 9.04%",
        }
        r = c.post("/api/v1/notifications", headers=h, json=payload)
        assert r.status_code == 201
        body = r.json()
        nid = body["id"]
        assert body["dismissed_at"] is None
        assert body["title"] == payload["title"]

        # 列出
        lst = c.get("/api/v1/notifications", headers=h).json()
        assert len(lst) == 1 and lst[0]["id"] == nid

        # 标记已读
        r = c.post(f"/api/v1/notifications/{nid}/read", headers=h)
        assert r.status_code == 200
        assert r.json()["dismissed_at"] is not None

        # 再标一次幂等，不会拉新时间戳
        ts1 = r.json()["dismissed_at"]
        r2 = c.post(f"/api/v1/notifications/{nid}/read", headers=h)
        assert r2.json()["dismissed_at"] == ts1

        # 标全部已读
        c.post("/api/v1/notifications", headers=h, json={"title": "t2"})
        c.post("/api/v1/notifications", headers=h, json={"title": "t3"})
        c.post("/api/v1/notifications/read-all", headers=h)
        all_items = c.get("/api/v1/notifications", headers=h).json()
        assert all(x["dismissed_at"] is not None for x in all_items)

        # 删一条
        r = c.delete(f"/api/v1/notifications/{nid}", headers=h)
        assert r.status_code == 204
        assert len(c.get("/api/v1/notifications", headers=h).json()) == 2

        # 清空
        c.delete("/api/v1/notifications", headers=h)
        assert c.get("/api/v1/notifications", headers=h).json() == []


def test_notification_user_isolation(db):
    with TestClient(app) as c:
        t1 = _login(c, "notif_iso1")
        t2 = _login(c, "notif_iso2")
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}

        c.post("/api/v1/notifications", headers=h1, json={"title": "A 的通知"})
        c.post("/api/v1/notifications", headers=h2, json={"title": "B 的通知"})

        assert c.get("/api/v1/notifications", headers=h1).json()[0]["title"] == "A 的通知"
        assert c.get("/api/v1/notifications", headers=h2).json()[0]["title"] == "B 的通知"


def test_notification_unauth_blocked(db):
    with TestClient(app) as c:
        assert c.get("/api/v1/notifications").status_code == 401
        assert c.post("/api/v1/notifications", json={"title": "x"}).status_code == 401
