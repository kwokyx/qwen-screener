import json
import time

from fastapi.testclient import TestClient

from app.schemas.screener import FilterCondition, ScreenRequest
from app.main import app
from app.services import qwen_client, strategy_selector
from app.services.qwen_client.agent_planner import AgentPlanResult, AgentReactDecision


def _events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _stream_events(client: TestClient, query: str, context: dict | None = None) -> list[dict]:
    payload = {"query": query}
    if context is not None:
        payload["context"] = context
    with client.stream("POST", "/api/v1/screener/nl/stream", json=payload) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    return _events(body)


def _context_from_events(events: list[dict]) -> dict:
    payload = next(
        event for event in reversed(events)
        if event["type"] in {"result", "agent", "design"}
    )
    result = None
    if payload["type"] == "result":
        result = {
            "total": payload["total"],
            "offset": payload.get("offset", 0),
            "limit": payload.get("limit", 50),
            "trade_date": payload.get("trade_date"),
            "items": payload.get("items", []),
            "parsed_conditions": payload.get("parsed_conditions", []),
        }
    return {
        "last_query": payload.get("query") or "",
        "last_plan": payload.get("plan"),
        "last_answer": payload.get("answer", ""),
        "last_conditions": payload.get("conditions") or payload.get("parsed_conditions") or [],
        "last_result": result,
        "last_tool_calls": payload.get("tool_calls", []),
        "recent_turns": [],
    }


def _event_types(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def _assert_safe_stop(events: list[dict], expected_reason: str | None = None) -> dict:
    event_types = _event_types(events)
    assert "agent" in event_types
    assert "parsed" not in event_types
    assert "screening" not in event_types
    assert "result" not in event_types
    terminal = next(event for event in events if event["type"] == "agent")
    assert terminal["plan"]["tool"] == "ask_clarification"
    assert terminal["plan"]["ai_used"] is False
    assert terminal["fallback_reason"]
    if expected_reason:
        assert expected_reason in terminal["fallback_reason"]
    return terminal


def _patch_react_from_single_plan(monkeypatch, planner):
    """Adapt existing single-tool fake planners to the ReAct step API."""

    def plan_react_step(query, context=None, observations=None, step_index=1):
        if observations:
            return AgentReactDecision(
                kind="final",
                public_reason="模型基于工具 observation 生成最终回答。",
                final_answer="已根据工具结果生成回答。",
            )
        plan = planner(query, context)
        if plan is None:
            return None
        return AgentReactDecision(
            kind="action",
            public_reason=plan.reasoning,
            plan=plan,
        )

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", planner)
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", plan_react_step)


def test_nl_stream_multiturn_agent_regression_with_fake_qwen(db, seed_stocks, monkeypatch):
    """Stable SSE regression for the public chat demo flow.

    The model planner is faked, but the SSE endpoint, context reuse and local
    tool execution are real.
    """
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def plan_agent_turn(query, context=None):
        reusable_conditions = [
            FilterCondition(field="industry", op="in", value=["银行"]),
            FilterCondition(field="pe", op="lt", value=15),
        ]
        if query == "PE 低于 15 且 PB 小于 2 的银行股":
            return AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="AI 解析低估值银行筛选",
                conditions=reusable_conditions,
                sort_by="market_cap",
                sort_desc=True,
            )
        if query == "为什么这些股票排在前面":
            return AgentPlanResult(
                tool="explain_result",
                tool_label="结果解释",
                reasoning="解释上一轮排序和条件",
            )
        if query == "按股息率排序":
            return AgentPlanResult(
                tool="sort_results",
                tool_label="结果排序",
                reasoning="沿用上一轮条件并按股息率排序",
                sort_by="dividend_yield",
                sort_desc=True,
            )
        if query == "换一批":
            return AgentPlanResult(
                tool="paginate_results",
                tool_label="结果分页",
                reasoning="沿用上一轮条件查看下一批",
                offset=0,
            )
        if query == "查看第一只详情":
            return AgentPlanResult(
                tool="stock_detail",
                tool_label="个股详情",
                reasoning="查看上一轮第一只股票详情",
            )
        if query == "帮我设计一个稳健的选股策略，先别执行":
            return AgentPlanResult(
                tool="strategy_design",
                tool_label="策略设计",
                reasoning="先设计策略，不执行筛选",
                extra={
                    "quantitative_conditions": ["ROE 不低于 20%", "PE 低于 20"],
                    "framework": "质量与估值并重",
                },
            )
        if query == "现在执行":
            return AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="执行上一轮稳健策略",
                conditions=[
                    FilterCondition(field="pe", op="lt", value=20),
                    FilterCondition(field="roe", op="gt", value=20),
                ],
                sort_by="roe",
                sort_desc=True,
            )
        if query == "你好":
            return AgentPlanResult(
                tool="ask_clarification",
                tool_label="补充追问",
                reasoning="闲聊问候不应筛选",
                extra={"question": "你好。请补充行业、风格或指标后我再筛选。"},
            )
        if query == "可以，做吧":
            return AgentPlanResult(
                tool="ask_clarification",
                tool_label="补充追问",
                reasoning="当前上下文没有可执行条件",
                extra={"question": "我还没有可以直接执行的上一轮条件。请先描述选股目标。"},
            )
        raise AssertionError(f"unexpected query: {query}")

    _patch_react_from_single_plan(monkeypatch, plan_agent_turn)

    client = TestClient(app)
    context = {}
    cases = [
        ("PE 低于 15 且 PB 小于 2 的银行股", "stock_screen", True, "result", False, 1),
        ("为什么这些股票排在前面", "explain_result", False, "agent", False, 0),
        ("按股息率排序", "sort_results", False, "result", False, 1),
        ("换一批", "paginate_results", False, "result", False, 1),
        ("查看第一只详情", "stock_detail", False, "agent", False, 0),
        ("帮我设计一个稳健的选股策略，先别执行", "strategy_design", False, "design", False, 0),
        ("现在执行", "stock_screen", True, "result", False, 0),
        ("你好", "ask_clarification", False, "agent", False, 0),
        ("可以，做吧", "ask_clarification", False, "agent", False, 0),
    ]

    for query, expected_tool, should_screen, terminal_type, expected_ai_used, min_total in cases:
        events = _stream_events(client, query, context=context)
        event_types = _event_types(events)
        terminal = next(event for event in reversed(events) if event["type"] == terminal_type)

        assert terminal["plan"]["tool"] == expected_tool
        assert terminal["plan"]["ai_used"] is expected_ai_used
        assert "planning" in event_types
        assert isinstance(terminal["model_ms"], int)
        assert isinstance(terminal["tool_ms"], int)
        if expected_ai_used:
            assert terminal["fallback_reason"] is None
        else:
            assert terminal["model_ms"] == 0
            assert terminal["fallback_reason"] == "local_fast_path"
        assert event_types[-1] == "done"
        assert ("screening" in event_types) is should_screen
        assert ("result" in event_types) is (terminal_type == "result")
        if should_screen:
            assert event_types.index("parsed") < event_types.index("screening") < event_types.index("result")
            assert terminal["total"] >= min_total
            assert any(call["name"] == "stock_screen" for call in terminal["tool_calls"])
        elif terminal_type == "result":
            assert "parsed" not in event_types
            assert "screening" not in event_types
            assert terminal["total"] >= min_total
            assert any(call["name"] == "result_sort" for call in terminal["tool_calls"])
            assert not any(call["name"] == "stock_screen" for call in terminal["tool_calls"])
        else:
            assert "parsed" not in event_types
            assert "result" not in event_types

        if expected_tool == "stock_detail":
            detail_call = next(call for call in terminal["tool_calls"] if call["name"] == "stock_detail")
            assert detail_call["result"]["url"] == "/detail/600036.SH"
        if expected_tool == "ask_clarification":
            assert not any(call["name"] == "stock_screen" for call in terminal["tool_calls"])

        context = _context_from_events(events)


def test_nl_stream_no_context_model_failure_never_screens(db, seed_stocks, monkeypatch):
    """If the model fails on context-light turns, fallback must not screen all stocks."""
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def fail_plan(*_args, **_kwargs):
        raise RuntimeError("planner failure")

    def fail_screen(*_args, **_kwargs):
        raise AssertionError("no-context local fast-path should not execute screening")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", fail_plan)
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    client = TestClient(app)
    events = _stream_events(client, "你好", context={})
    terminal = next(event for event in reversed(events) if event["type"] == "agent")
    assert terminal["plan"]["tool"] == "ask_clarification"
    assert terminal["plan"]["ai_used"] is False
    assert terminal["model_ms"] == 0
    assert terminal["fallback_reason"] == "local_fast_path"

    for query in ("可以，做吧", "为什么这些股票排在前面"):
        events = _stream_events(client, query, context={})
        event_types = _event_types(events)
        terminal = next(event for event in reversed(events) if event["type"] == "agent")

        assert event_types[-1] == "done"
        assert "screening" not in event_types
        assert "result" not in event_types
        assert "parsed" not in event_types
        assert terminal["plan"]["tool"] == "ask_clarification"
        assert terminal["plan"]["ai_used"] is False
        assert terminal["model_ms"] == 0
        assert terminal["fallback_reason"] == "local_fast_path"

    events = _stream_events(client, "查看第一只详情", context={})
    event_types = _event_types(events)
    terminal = next(event for event in reversed(events) if event["type"] == "agent")
    assert event_types[-1] == "done"
    assert "screening" not in event_types
    assert "result" not in event_types
    assert "parsed" not in event_types
    assert terminal["plan"]["tool"] == "ask_clarification"
    assert terminal["plan"]["ai_used"] is False
    assert terminal["model_ms"] == 0
    assert terminal["fallback_reason"] == "local_fast_path"
    assert not any(call["name"] == "stock_screen" for call in terminal["tool_calls"])


def test_nl_stream_deterministic_screen_query_skips_ai_before_tool(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("deterministic screen should not probe AI health")),
    )
    calls = {"planner": 0}

    def plan_react_step(*_args, **_kwargs):
        calls["planner"] += 1
        raise AssertionError("deterministic screen should not call ReAct planner")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", plan_react_step)

    client = TestClient(app)
    events = _stream_events(client, "PE 低于 15 且 PB 小于 2 的银行股", context={})
    event_types = _event_types(events)

    assert event_types.index("parsed") < event_types.index("screening") < event_types.index("result")
    assert event_types[-1] == "done"
    assert calls["planner"] == 0
    assert "react_step" not in event_types
    assert {"tool_start", "tool_observation", "tool_done", "final"} <= set(event_types)
    result = next(event for event in events if event["type"] == "result")
    assert result["plan"]["tool"] == "stock_screen"
    assert result["plan"]["ai_used"] is False
    assert result["ai_status"] == {
        "configured": True,
        "used": False,
        "source": "local_deterministic",
        "label": "本地处理",
        "fallback": False,
    }
    assert result["model_ms"] == 0
    assert result["fallback_reason"] == "local_fast_path"
    assert result["parsed_conditions"]
    assert [(condition["field"], condition["op"], condition["value"]) for condition in result["parsed_conditions"]] == [
        ("pe", "lt", 15),
        ("pb", "lt", 2),
        ("industry", "in", ["银行"]),
    ]
    assert any(
        call["name"] == "stock_screen" and call["result"]["total"] == result["total"]
        for call in result["tool_calls"]
    )


def test_nl_stream_blue_chip_dividend_query_uses_local_screen(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("deterministic screen should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("deterministic screen should not call model")),
    )

    client = TestClient(app)
    events = _stream_events(client, "股息率超过 5% 的大蓝筹", context={})
    event_types = _event_types(events)
    result = next(event for event in events if event["type"] == "result")

    assert event_types.index("parsed") < event_types.index("screening") < event_types.index("result")
    assert result["plan"]["tool"] == "stock_screen"
    assert result["plan"]["ai_used"] is False
    assert result["model_ms"] == 0
    assert result["fallback_reason"] == "local_fast_path"
    assert [(condition["field"], condition["op"], condition["value"]) for condition in result["parsed_conditions"]] == [
        ("dividend_yield", "gt", 5),
        ("market_cap", "gt", 500),
    ]


def test_nl_stream_model_failure_preserves_attempted_model_ms(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def slow_fail_plan(_query, context=None, observations=None, step_index=1):
        time.sleep(0.02)
        raise RuntimeError("planner timeout test")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", slow_fail_plan)

    client = TestClient(app)
    events = _stream_events(client, "找最近强势突破的股票", context={})
    event_types = _event_types(events)
    result = next(event for event in events if event["type"] == "agent")

    assert "screening" not in event_types
    assert "result" not in event_types
    assert result["plan"]["tool"] == "ask_clarification"
    assert result["plan"]["ai_used"] is False
    assert result["model_ms"] > 0
    assert result["fallback_reason"]


def test_nl_stream_blocks_unsupported_profit_cagr_without_partial_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("unsupported CAGR query must not execute a partial screen")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("unsupported preflight should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported preflight should not call the model")),
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    client = TestClient(app)
    events = _stream_events(client, "找出 PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股", context={})
    event_types = _event_types(events)

    assert "screening" not in event_types
    assert "result" not in event_types
    assert event_types[-1] == "done"
    terminal = next(event for event in events if event["type"] == "agent")
    assert terminal["plan"]["tool"] == "ask_clarification"
    assert terminal["plan"]["ai_configured"] is True
    assert terminal["plan"]["ai_used"] is False
    assert terminal["conditions"] == []
    assert terminal["model_ms"] == 0
    assert terminal["fallback_reason"] == "local_fast_path"
    assert "近三年净利润复合增速" in terminal["answer"]


def test_nl_stream_design_request_skips_ai_and_screening(db, seed_stocks, monkeypatch):
    def fail_stream_call(_prompt):
        raise AssertionError("strategy design should not stream nl_to_filter")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
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
    terminal = _assert_safe_stop(events, "AI 服务已配置但当前不可用")
    assert "不执行筛选" in terminal["answer"]


def test_nl_stream_clarification_request_skips_screening(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
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


def test_nl_stream_confirmation_without_context_skips_screening(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "可以，做吧", "context": {}},
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
    assert "还没有可以直接执行" in agent["answer"]


def test_nl_stream_confirmation_reuses_previous_design_conditions(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={
            "query": "可以，做吧",
            "context": {
                "last_plan": {
                    "tool": "strategy_design",
                    "logic": "AND",
                    "sort_by": "roe",
                    "sort_desc": True,
                },
                "last_conditions": [
                    {"field": "pe", "op": "lt", "value": 20},
                    {"field": "roe", "op": "gt", "value": 20},
                ],
            },
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = _event_types(events)
    assert "result" in event_types
    assert "screening" in event_types
    result = next(event for event in events if event["type"] == "result")
    assert result["plan"]["tool"] == "stock_screen"
    assert result["plan"]["ai_used"] is False
    assert result["model_ms"] == 0
    assert result["fallback_reason"] == "local_fast_path"
    assert result["parsed_conditions"] == [
        {"field": "pe", "op": "lt", "value": 20},
        {"field": "roe", "op": "gt", "value": 20},
    ]


def test_nl_one_shot_uses_context_for_confirmation(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/screener/nl",
        json={
            "query": "可以，做吧",
            "context": {
                "last_plan": {
                    "tool": "strategy_design",
                    "logic": "AND",
                    "sort_by": "roe",
                    "sort_desc": True,
                },
                "last_conditions": [
                    {"field": "pe", "op": "lt", "value": 20},
                    {"field": "roe", "op": "gt", "value": 20},
                ],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 0
    assert body["parsed_conditions"] == [
        {"field": "pe", "op": "lt", "value": 20},
        {"field": "roe", "op": "gt", "value": 20},
    ]


def test_nl_stream_adjusts_previous_conditions(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={
            "query": "再严格一点",
            "context": {
                "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "roe", "sort_desc": True},
                "last_conditions": [
                    {"field": "pe", "op": "lt", "value": 20},
                    {"field": "roe", "op": "gt", "value": 20},
                ],
            },
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = _event_types(events)
    assert "result" in event_types
    assert "screening" in event_types
    result = next(event for event in events if event["type"] == "result")
    assert result["plan"]["tool"] == "stock_screen"
    assert result["plan"]["ai_used"] is False
    assert result["model_ms"] == 0
    assert result["fallback_reason"] == "local_fast_path"


def test_nl_stream_adjustment_without_context_skips_screening(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "再严格一点", "context": {}},
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
    assert "还没有上一轮条件" in agent["answer"]


def test_nl_stream_explain_result_uses_context_without_rescreen(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("explain fast path should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("explain fast path should not call model")),
    )
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
    assert agent["plan"]["ai_used"] is False
    assert agent["model_ms"] == 0
    assert agent["fallback_reason"] == "local_fast_path"
    assert "不重新筛选" in agent["answer"]


def test_nl_stream_stock_detail_uses_context_without_rescreen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("stock_detail should not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("stock detail fast path should not probe AI health")),
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={
            "query": "查看第一只详情",
            "context": {
                "last_result": {
                    "total": 2,
                    "items": [
                        {"code": "600036.SH", "name": "招商银行"},
                        {"code": "688981.SH", "name": "中芯国际"},
                    ],
                    "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
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
    terminal = next(event for event in reversed(events) if event["type"] == "agent")
    assert terminal["plan"]["tool"] == "stock_detail"
    assert terminal["fallback_reason"] == "local_fast_path"
    detail_call = next(call for call in terminal["tool_calls"] if call["name"] == "stock_detail")
    assert detail_call["result"]["url"] == "/detail/600036.SH"


def test_nl_stream_named_stock_detail_uses_local_lookup_without_ai(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("stock_detail should not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("stock detail lookup should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stock detail lookup should not call model")),
    )

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "我想看一下招商银行的详情", "context": {}},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "agent" in event_types
    assert "screening" not in event_types
    assert "result" not in event_types
    terminal = next(event for event in reversed(events) if event["type"] == "agent")
    assert terminal["plan"]["tool"] == "stock_detail"
    assert terminal["fallback_reason"] == "local_fast_path"
    detail_call = next(call for call in terminal["tool_calls"] if call["name"] == "stock_detail")
    assert detail_call["result"]["url"] == "/detail/600036.SH"


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
    _assert_safe_stop(events, "AI 服务已配置但当前不可用")


def test_nl_stream_stock_screen_uses_model_planner(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    _patch_react_from_single_plan(
        monkeypatch,
        lambda _query, _context=None: AgentPlanResult(
            tool="stock_screen",
            tool_label="结构化股票筛选",
            reasoning="AI 解析测试",
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
        json={"query": "请根据模型做一次筛选观察"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "parsed" in event_types
    assert "screening" in event_types
    assert "result" in event_types
    assert "tool_call" in event_types
    assert event_types.index("parsed") < event_types.index("screening") < event_types.index("result")

    thinking_texts = [e["text"] for e in events if e["type"] == "thinking"]
    assert any("已选择工具" in t for t in thinking_texts)
    assert any("参数校验已完成" in t for t in thinking_texts)
    assert any("正在执行本地工具：股票筛选" in t for t in thinking_texts)
    assert any("已生成结果" in t for t in thinking_texts)

    parsed = next(event for event in events if event["type"] == "parsed")
    result = next(event for event in events if event["type"] == "result")
    assert parsed["plan"]["tool"] == "stock_screen"
    assert parsed["plan"]["ai_used"] is True
    assert parsed["ai_status"] == {
        "configured": True,
        "used": True,
        "source": "ai_agent",
        "label": "AI Agent",
        "fallback": False,
    }
    assert parsed["tool_calls"]
    assert parsed["model_ms"] >= 0
    assert parsed["tool_ms"] == 0
    assert result["total"] == 1
    assert result["model_ms"] >= 0
    assert result["tool_ms"] >= 0
    assert result["fallback_reason"] is None
    assert result["items"][0]["code"] == "600036.SH"
    assert any(call["name"] == "stock_screen" and call["result"]["total"] == 1 for call in result["tool_calls"])


def test_nl_stream_react_tool_result_uses_deterministic_final(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    calls = []

    def plan_react_step(query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="先筛选低估值银行股。",
            plan=AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="AI 解析低估值银行筛选",
                conditions=[
                    FilterCondition(field="industry", op="in", value=["银行"]),
                    FilterCondition(field="pe", op="lt", value=15),
                ],
                sort_by="dividend_yield",
                sort_desc=True,
            ),
        )

    def spy_plan_react_step(query, context=None, observations=None, step_index=1):
        calls.append({"step_index": step_index, "observation_count": len(observations or [])})
        if observations:
            raise AssertionError("successful tool result should not request a model final summary")
        return plan_react_step(query, context=context, observations=observations, step_index=step_index)

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", spy_plan_react_step)

    client = TestClient(app)
    events = _stream_events(client, "请根据模型判断做一次筛选观察", context={})
    event_types = _event_types(events)

    assert {"react_step", "tool_start", "tool_observation", "tool_done", "final"} <= set(event_types)
    assert next(event for event in events if event["type"] == "react_step")["timing_phase"] == "model_action"
    assert next(event for event in events if event["type"] == "tool_done")["timing_phase"] == "tool_execution"
    assert next(event for event in events if event["type"] == "final")["timing_phase"] == "local_final"
    result = next(event for event in events if event["type"] == "result")
    assert "当前命中 1 只" in result["answer"]
    assert "招商银行" in result["answer"]
    assert result["completion_reason"] is None
    assert result["react_steps"]
    assert calls == [{"step_index": 1, "observation_count": 0}]


def test_nl_stream_react_tool_result_skips_final_timeout(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    calls = []

    def plan_react_step(query, context=None, observations=None, step_index=1):
        calls.append({"step_index": step_index, "observation_count": len(observations or [])})
        if observations:
            raise AssertionError("successful tool result should not wait for a final model call")
        return AgentReactDecision(
            kind="action",
            public_reason="先筛选低估值银行股。",
            plan=AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="AI 解析低估值银行筛选",
                conditions=[
                    FilterCondition(field="industry", op="in", value=["银行"]),
                    FilterCondition(field="pe", op="lt", value=15),
                ],
                sort_by="dividend_yield",
                sort_desc=True,
            ),
        )

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", plan_react_step)
    monkeypatch.setattr(strategy_selector.qwen_client, "last_plan_failure_reason", lambda: "模型 ReAct 步骤超过 12 秒")

    client = TestClient(app)
    events = _stream_events(client, "请根据模型判断做一次筛选观察", context={})
    result = next(event for event in events if event["type"] == "result")

    assert result["total"] == 1
    assert result["plan"]["ai_used"] is True
    assert result["fallback_reason"] is None
    assert result["completion_reason"] is None
    assert not any("最终总结未完成" in warning for warning in result["warnings"])
    assert next(event for event in events if event["type"] == "final")["timing_phase"] == "local_final"
    assert calls == [{"step_index": 1, "observation_count": 0}]


def test_nl_stream_react_stops_after_successful_tool_action(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    plan = AgentPlanResult(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="重复动作测试",
        conditions=[
            FilterCondition(field="industry", op="in", value=["银行"]),
            FilterCondition(field="pe", op="lt", value=15),
        ],
        sort_by="dividend_yield",
        sort_desc=True,
    )

    calls = []

    def plan_react_step(query, context=None, observations=None, step_index=1):
        calls.append({"step_index": step_index, "observation_count": len(observations or [])})
        if observations:
            raise AssertionError("successful tool action should finish without duplicate model actions")
        return AgentReactDecision(kind="action", public_reason="重复选择同一工具", plan=plan)

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", plan_react_step)

    client = TestClient(app)
    events = _stream_events(client, "请根据模型测试重复动作保护", context={})
    result = next(event for event in events if event["type"] == "result")

    assert result["total"] == 1
    assert result["fallback_reason"] is None
    assert result["completion_reason"] is None
    assert next(event for event in events if event["type"] == "final")["timing_phase"] == "local_final"
    assert calls == [{"step_index": 1, "observation_count": 0}]


def test_nl_stream_preflights_unsupported_metric_before_model_action(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("unsupported preflight must not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported preflight should not call model action")),
    )

    client = TestClient(app)
    events = _stream_events(client, "找出 PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股", context={})
    event_types = _event_types(events)
    terminal = next(event for event in events if event["type"] == "agent")

    assert "screening" not in event_types
    assert "result" not in event_types
    assert terminal["plan"]["tool"] == "ask_clarification"
    assert terminal["plan"]["ai_configured"] is True
    assert terminal["plan"]["ai_used"] is False
    assert terminal["model_ms"] == 0
    assert terminal["fallback_reason"] == "local_fast_path"
    assert "近三年净利润复合增速" in terminal["answer"]


def test_nl_stream_model_chooses_strategy_design_skips_screening(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    _patch_react_from_single_plan(
        monkeypatch,
        lambda _query, _context=None: AgentPlanResult(
            tool="strategy_design",
            tool_label="策略设计",
            reasoning="设计请求",
            extra={"quantitative_conditions": ["ROE>15", "PE<25"]},
        ),
    )

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={"query": "帮我设计一个稳健的选股策略"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _events(body)
    event_types = [event["type"] for event in events]
    assert "design" in event_types
    assert "screening" not in event_types
    assert "result" not in event_types

    thinking_texts = [e["text"] for e in events if e["type"] == "thinking"]
    assert any("已选择工具" in t for t in thinking_texts)
    assert any("参数校验已完成" in t for t in thinking_texts)
    assert any("正在整理响应：策略设计" in t for t in thinking_texts)

    design = next(event for event in events if event["type"] == "design")
    assert design["plan"]["tool"] == "strategy_design"
    assert design["plan"]["ai_used"] is True


def test_nl_stream_local_explain_result_preempts_model(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("local explain should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local explain should not call model")),
    )

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/screener/nl/stream",
        json={
            "query": "为什么这些股票会被选出来？",
            "context": {
                "last_result": {
                    "total": 2,
                    "items": [{"code": "600036.SH", "name": "招行"}],
                    "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
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

    thinking_texts = [e["text"] for e in events if e["type"] == "thinking"]
    assert any("正在整理响应：结果解释" in t for t in thinking_texts)

    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "explain_result"
    assert agent["plan"]["ai_used"] is False
    assert agent["model_ms"] == 0
    assert agent["fallback_reason"] == "local_fast_path"


def test_nl_stream_model_chooses_strategy_select(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    _patch_react_from_single_plan(
        monkeypatch,
        lambda _query, _context=None: AgentPlanResult(
            tool="strategy_select",
            tool_label="策略选股",
            reasoning="突破策略",
            strategy_id="turtle_breakout",
            limit=5,
        ),
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
    event_types = [event["type"] for event in events]
    assert "planned" in event_types
    assert "screening" in event_types
    assert "agent" in event_types
    assert event_types.index("planned") < event_types.index("screening") < event_types.index("agent")

    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "strategy_select"
    assert agent["plan"]["ai_used"] is True


def test_nl_stream_ai_unavailable_returns_chat_without_screening(db, seed_stocks, monkeypatch):
    """AI unavailable must not silently execute model-routed stock tools."""
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "test unavailable"},
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
    event_types = [event["type"] for event in events]
    thinking_texts = [e["text"] for e in events if e["type"] == "thinking"]
    assert any("正在选择下一步" in t for t in thinking_texts)
    assert any("已选择工具" in t for t in thinking_texts)
    assert any("参数校验已完成" in t for t in thinking_texts)
    assert any("已生成结果" in t for t in thinking_texts)
    assert "parsed" not in event_types
    assert "screening" not in event_types
    assert "result" not in event_types
    agent = next(event for event in events if event["type"] == "agent")
    assert agent["plan"]["tool"] == "ask_clarification"
    assert agent["ai_status"] == {
        "configured": True,
        "used": False,
        "source": "chat_only",
        "label": "普通回复",
        "fallback": False,
    }
