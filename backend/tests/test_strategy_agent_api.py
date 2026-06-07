from fastapi.testclient import TestClient

from app.main import app
from app.schemas.screener import FilterCondition
from app.services import strategy_selector
from app.services.qwen_client.agent_planner import AgentPlanResult, AgentReactDecision


def test_strategy_agent_api_uses_model_action_before_screen(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def plan_react_step(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="模型判断需要执行股票筛选。",
            plan=AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="模型解析低估值银行",
                conditions=[
                    FilterCondition(field="industry", op="in", value=["银行"]),
                    FilterCondition(field="pe", op="lt", value=15),
                ],
                sort_by="dividend_yield",
                sort_desc=True,
            ),
        )

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", plan_react_step)

    client = TestClient(app)
    response = client.post("/api/v1/strategy/agent", json={"query": "低估值银行", "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["tool"] == "stock_screen"
    assert body["plan"]["ai_used"] is True
    assert body["screen_result"]["total"] == 1
    assert body["screen_result"]["items"][0]["code"] == "600036.SH"
    assert body["react_steps"][-1]["fallback_reason"] is None


def test_strategy_agent_api_model_final_is_plain_reply(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: AgentReactDecision(
            kind="final",
            public_reason="模型判断这是普通说明请求。",
            final_answer="我是这个项目里的有界选股 Agent，可以在需要时调用筛选、策略和详情工具。",
        ),
    )
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plain reply must not screen")),
    )

    client = TestClient(app)
    response = client.post("/api/v1/strategy/agent", json={"query": "这个 Agent 是什么", "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["tool"] == "ask_clarification"
    assert body["plan"]["tool_label"] == "普通回复"
    assert body["plan"]["ai_used"] is True
    assert body["screen_result"] is None
    assert body["strategy_result"] is None
    assert [call["name"] for call in body["tool_calls"]] == ["tool_router"]
    assert "有界选股 Agent" in body["answer"]
    assert body["react_steps"][-1]["timing_phase"] == "model_final"


def test_strategy_agent_api_ai_unavailable_does_not_local_fallback(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "test unavailable"},
    )
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AI unavailable must not screen locally")),
    )
    monkeypatch.setattr(
        strategy_selector,
        "run_strategy_selection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AI unavailable must not select strategy locally")),
    )

    client = TestClient(app)
    response = client.post("/api/v1/strategy/agent", json={"query": "低估值银行", "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["tool"] == "ask_clarification"
    assert body["plan"]["tool_label"] == "普通回复"
    assert body["plan"]["ai_used"] is False
    assert body["screen_result"] is None
    assert body["strategy_result"] is None
    assert "不执行筛选" in body["answer"]
    assert "AI 服务已配置但当前不可用" in body["warnings"][0]


def test_strategy_agent_api_unsupported_metric_still_preflights(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("unsupported preflight should not probe AI")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported preflight should not call model")),
    )
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported preflight must not screen")),
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/strategy/agent",
        json={"query": "PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["tool"] == "ask_clarification"
    assert body["plan"]["ai_used"] is False
    assert body["screen_result"] is None
    assert "近三年净利润复合增速" in body["answer"]
