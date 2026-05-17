"""Chat 对话历史持久化：POST 创建 / GET 列表 / DELETE 单条 / DELETE 全部。"""
from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient, u: str, p: str = "abcd1234"):
    client.post("/api/v1/auth/register", json={"username": u, "password": p})
    r = client.post("/api/v1/auth/login", data={"username": u, "password": p})
    return r.json()["access_token"]


def test_chat_sessions_crud(db):
    with TestClient(app) as c:
        token = _login(c, "chat_user1")
        h = {"Authorization": f"Bearer {token}"}

        # 起步空
        assert c.get("/api/v1/chat/sessions", headers=h).json() == []

        # POST 一条
        payload = {
            "query": "低估值高分红的银行股",
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 8}],
            "items": [{"code": "600036.SH", "name": "招商银行"}],
            "total": 12,
            "screen_meta": {"runtime_ms": 38},
        }
        r = c.post("/api/v1/chat/sessions", headers=h, json=payload)
        assert r.status_code == 201
        sid = r.json()["id"]
        assert r.json()["query"] == payload["query"]
        assert r.json()["parsed_conditions"] == payload["parsed_conditions"]

        # GET 列表，包含新建的一条
        lst = c.get("/api/v1/chat/sessions", headers=h).json()
        assert len(lst) == 1 and lst[0]["id"] == sid
        # 字段完整
        assert lst[0]["items"][0]["code"] == "600036.SH"
        assert lst[0]["screen_meta"] == {"runtime_ms": 38}

        # DELETE 单条
        r = c.delete(f"/api/v1/chat/sessions/{sid}", headers=h)
        assert r.status_code == 204
        assert c.get("/api/v1/chat/sessions", headers=h).json() == []

        # DELETE 不存在的 → 404
        assert c.delete(f"/api/v1/chat/sessions/{sid}", headers=h).status_code == 404


def test_chat_sessions_clear_all(db):
    with TestClient(app) as c:
        token = _login(c, "chat_user2")
        h = {"Authorization": f"Bearer {token}"}

        for i in range(3):
            c.post("/api/v1/chat/sessions", headers=h, json={"query": f"测试查询 {i}"})
        assert len(c.get("/api/v1/chat/sessions", headers=h).json()) == 3

        r = c.delete("/api/v1/chat/sessions", headers=h)
        assert r.status_code == 204
        assert c.get("/api/v1/chat/sessions", headers=h).json() == []


def test_chat_sessions_isolation_between_users(db):
    """两个用户互不干扰：A 的历史 B 看不到。"""
    with TestClient(app) as c:
        t1 = _login(c, "chat_iso1")
        t2 = _login(c, "chat_iso2")
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}

        c.post("/api/v1/chat/sessions", headers=h1, json={"query": "A 的查询"})
        c.post("/api/v1/chat/sessions", headers=h2, json={"query": "B 的查询"})

        l1 = c.get("/api/v1/chat/sessions", headers=h1).json()
        l2 = c.get("/api/v1/chat/sessions", headers=h2).json()
        assert len(l1) == 1 and l1[0]["query"] == "A 的查询"
        assert len(l2) == 1 and l2[0]["query"] == "B 的查询"


def test_chat_sessions_unauth_blocked(db):
    """未带 token 访问应 401。"""
    with TestClient(app) as c:
        assert c.get("/api/v1/chat/sessions").status_code == 401
        assert c.post("/api/v1/chat/sessions", json={"query": "x"}).status_code == 401
