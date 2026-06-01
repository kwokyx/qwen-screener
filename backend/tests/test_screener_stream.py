import json

from fastapi.testclient import TestClient

from app.schemas.screener import FilterCondition, ScreenRequest
from app.main import app
from app.services import qwen_client, strategy_selector


def _events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def test_nl_stream_design_request_skips_ai_and_screening(db, seed_stocks, monkeypatch):
    def fail_stream_call(_prompt):
        raise AssertionError("strategy design should not stream nl_to_filter")

    monkeypatch.setattr(qwen_client, "stream_call", fail_stream_call)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "帮我设计一个稳健的选股策略，列出量化条件"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "design" in event_types
    assert "screening" not in event_types
    assert "result" not in event_types

    design = next(event for event in events if event["type"] == "design")
    assert design["plan"]["tool"] == "strategy_design"
    assert len(design["conditions"]) == 7
    assert "先不执行筛选" in design["answer"]


def test_nl_stream_clarification_request_skips_screening(db, seed_stocks):
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "帮我选点好股票"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "agent" in event_types
    assert "screening" not in event_types
    assert "result" not in event_types

    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "ask_clarification"
    assert "我先不筛股票" in agent["answer"]


def test_nl_stream_explain_result_uses_context_without_rescreen(db, seed_stocks):
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={
            "query": "为什么这些股票会被选出来？",
            "context": {
                "last_result": {
                    "total": 1,
                    "items": [
                        {
                            "code": "600036.SH",
                            "name": "招商银行",
                            "industry": "银行",
                            "pe": 6.5,
                            "roe": 16.5,
                            "dividend_yield": 4.1,
                        }
                    ],
                    "parsed_conditions": [
                        {"field": "industry", "op": "in", "value": ["银行"]},
                        {"field": "pe", "op": "lt", "value": 15},
                    ],
                }
            },
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "agent" in event_types
    assert "screening" not in event_types
    assert "result" not in event_types

    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "explain_result"
    assert "招商银行" in agent["answer"]
    assert "不重新筛选" in agent["answer"]


def test_nl_stream_routes_strategy_select(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "test"},
    )

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "找最近强势突破的股票"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "strategy_select"
    assert agent["result"]["total"] >= 0


def test_nl_stream_stock_screen_uses_agent_parser(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "parse_nl_query",
        lambda _query: ScreenRequest(
            conditions=[
                FilterCondition(field="industry", op="in", value=["银行"]),
                FilterCondition(field="pe", op="lt", value=15),
            ],
            sort_by="dividend_yield",
            sort_desc=True,
        ),
    )

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "低估值高分红的银行股"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "parsed" in event_types
    assert "screening" in event_types
    assert "result" in event_types

    parsed = next(event for event in events if event["type"] == "parsed")
    result = next(event for event in events if event["type"] == "result")
    assert parsed["plan"]["tool"] == "stock_screen"
    assert result["total"] == 1
    assert result["items"][0]["code"] == "600036.SH"
