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
            "context_id": "ctx-chat-user1-turn1",
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 8}],
            "items": [{"code": "600036.SH", "name": "招商银行"}],
            "total": 12,
            "screen_meta": {"runtime_ms": 38},
            "agent_plan": {"tool": "stock_screen", "sort_by": "score"},
            "agent_answer": "命中招商银行等股票",
            "tool_trace": ["tool_router -> stock_screen"],
            "tool_calls": [{"name": "stock_screen", "result": {"total": 12}}],
            "result_snapshot": {
                "total": 12,
                "items": [{"code": "600036.SH", "name": "招商银行"}],
                "parsed_conditions": [{"field": "pe", "op": "lt", "value": 8}],
            },
        }
        r = c.post("/api/v1/chat/sessions", headers=h, json=payload)
        assert r.status_code == 201
        sid = r.json()["id"]
        assert r.json()["query"] == payload["query"]
        assert r.json()["context_id"] == payload["context_id"]
        assert r.json()["parsed_conditions"] == payload["parsed_conditions"]
        assert r.json()["agent_plan"] == payload["agent_plan"]
        assert r.json()["agent_answer"] == payload["agent_answer"]
        assert r.json()["tool_calls"][0]["name"] == "stock_screen"
        assert r.json()["result_snapshot"]["total"] == 12

        # GET 列表，包含新建的一条
        lst = c.get("/api/v1/chat/sessions", headers=h).json()
        assert len(lst) == 1 and lst[0]["id"] == sid
        # 字段完整
        assert lst[0]["items"][0]["code"] == "600036.SH"
        assert lst[0]["screen_meta"] == {"runtime_ms": 38}
        by_ctx = c.get(f"/api/v1/chat/sessions/context/{payload['context_id']}", headers=h)
        assert by_ctx.status_code == 200
        assert by_ctx.json()["id"] == sid

        # PUT 覆盖同一条会话，screen_meta.thread 用于保存多轮对话
        update_payload = {
            "query": "低估值高分红的银行股，继续执行",
            "context_id": "ctx-chat-user1-turn2",
            "parsed_conditions": [{"field": "dividend_yield", "op": "gte", "value": 5}],
            "items": [{"code": "000001.SZ", "name": "平安银行"}],
            "total": 35,
            "screen_meta": {
                "session_title": "低估值高分红银行",
                "thread": [
                    {"query": "帮我设计低估值高分红银行策略", "agentAnswer": "先看估值和股息"},
                    {"query": "可以，做吧", "result": {"items": [], "total": 35}},
                ],
            },
            "agent_plan": {"tool": "stock_screen", "sort_by": "dividend_yield"},
            "agent_answer": "已沿用上一轮条件调整排序。",
            "tool_trace": ["result_sort -> dividend_yield"],
            "tool_calls": [{"name": "result_sort"}],
            "result_snapshot": {"total": 35, "items": [{"code": "000001.SZ", "name": "平安银行"}]},
        }
        r = c.put(f"/api/v1/chat/sessions/{sid}", headers=h, json=update_payload)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == sid
        assert data["query"] == update_payload["query"]
        assert data["context_id"] == "ctx-chat-user1-turn2"
        assert data["total"] == 35
        assert data["agent_plan"]["sort_by"] == "dividend_yield"
        assert len(data["screen_meta"]["thread"]) == 2

        # PUT 不存在的 → 404
        assert c.put("/api/v1/chat/sessions/999999", headers=h, json=payload).status_code == 404

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


def test_chat_session_context_upsert_and_isolation(db):
    with TestClient(app) as c:
        t1 = _login(c, "chat_ctx1")
        t2 = _login(c, "chat_ctx2")
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}
        payload = {
            "context_id": "ctx-shared",
            "query": "低估值高分红的银行股",
            "parsed_conditions": [{"field": "industry", "op": "eq", "value": "银行"}],
            "total": 1,
        }

        r1 = c.post("/api/v1/chat/sessions", headers=h1, json=payload)
        assert r1.status_code == 201
        sid = r1.json()["id"]
        r2 = c.post("/api/v1/chat/sessions", headers=h1, json={**payload, "query": "更新后的查询", "total": 2})
        assert r2.status_code == 201
        assert r2.json()["id"] == sid
        assert r2.json()["query"] == "更新后的查询"
        assert r2.json()["total"] == 2
        assert len(c.get("/api/v1/chat/sessions", headers=h1).json()) == 1

        assert c.get("/api/v1/chat/sessions/context/ctx-shared", headers=h1).status_code == 200
        assert c.get("/api/v1/chat/sessions/context/ctx-shared", headers=h2).status_code == 404


def test_chat_sessions_unauth_blocked(db):
    """未带 token 访问应 401。"""
    with TestClient(app) as c:
        assert c.get("/api/v1/chat/sessions").status_code == 401
        assert c.post("/api/v1/chat/sessions", json={"query": "x"}).status_code == 401
        assert c.get("/api/v1/chat/sessions/context/ctx-x").status_code == 401
