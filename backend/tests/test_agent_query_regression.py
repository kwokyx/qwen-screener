import time

import pytest

from app.schemas.screener import ALLOWED_FIELDS, FilterCondition
from app.services import agent_react, strategy_selector
from app.services.qwen_client.agent_planner import AgentPlanResult, AgentReactDecision


LAST_RESULT_CONTEXT = {
    "last_plan": {
        "tool": "stock_screen",
        "logic": "AND",
        "sort_by": "score",
        "sort_desc": True,
    },
    "last_conditions": [
        {"field": "pe", "op": "lt", "value": 15},
        {"field": "pb", "op": "lt", "value": 2},
        {"field": "industry", "op": "in", "value": ["银行"]},
    ],
    "last_result": {
        "total": 1,
        "offset": 0,
        "limit": 2,
        "items": [
            {"code": "600036.SH", "name": "招商银行", "industry": "银行", "pe": 6.5, "pb": 0.85, "roe": 16.5},
        ],
        "parsed_conditions": [
            {"field": "pe", "op": "lt", "value": 15},
            {"field": "pb", "op": "lt", "value": 2},
            {"field": "industry", "op": "in", "value": ["银行"]},
        ],
    },
}


def _condition_tuples(response):
    return [(cond.field, cond.op, cond.value) for cond in response.plan.conditions]


def _patch_no_ai(monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("local regression path should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local regression path should not call model planner")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_react_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local regression path should not call ReAct planner")),
    )


def _patch_react_decision(monkeypatch, decision):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(strategy_selector, "_ai_status", lambda: {"configured": True, "ok": True, "reason": None})
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", decision)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("PE 15 以下的银行股", [("pe", "lte", 15), ("industry", "in", ["银行"])]),
        ("PE 低于 15 且 PB 小于 2 的银行股", [("pe", "lt", 15), ("pb", "lt", 2), ("industry", "in", ["银行"])]),
        ("ROE 15%以上、净利润同比为正", [("roe", "gte", 15), ("profit_yoy", "gt", 0)]),
        ("ROE 大于 15 且最新季度净利润同比正增长的成长股", [("roe", "gt", 15), ("profit_yoy", "gt", 0)]),
        ("营收同比为正且净利润同比为正的主板股票", [("profit_yoy", "gt", 0), ("revenue_yoy", "gt", 0), ("market", "in", ["主板"])]),
        ("毛利率25%以上、负债率60%以下", [("gross_margin", "gte", 25), ("debt_ratio", "lte", 60)]),
        ("市值500亿以上的半导体", [("market_cap", "gte", 500), ("industry", "in", ["半导体"])]),
        ("收盘价20以下、换手率5%以上", [("turnover", "gte", 5), ("close", "lte", 20)]),
        ("低估值高分红的银行股", [("pe", "lt", 15), ("pb", "lt", 2), ("dividend_yield", "gt", 3), ("industry", "in", ["银行"])]),
        ("稳健低风险的主板股票", [("roe", "gt", 15), ("debt_ratio", "lt", 60), ("market_cap", "gt", 500), ("market", "in", ["主板"])]),
    ],
)
def test_supported_queries_use_local_fast_path(db, seed_stocks, monkeypatch, query, expected):
    _patch_no_ai(monkeypatch)

    response = strategy_selector.run_agent_selection(db, query, limit=10)

    assert response.plan.tool == "stock_screen"
    assert response.plan.ai_used is False
    assert response.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert response.screen_result is not None
    assert _condition_tuples(response) == expected
    assert {cond.field for cond in response.plan.conditions} <= ALLOWED_FIELDS
    if "成长股" in query:
        assert ("revenue_yoy", "gt", 20) not in _condition_tuples(response)
        assert ("profit_yoy", "gt", 20) not in _condition_tuples(response)


@pytest.mark.parametrize(
    ("query", "label"),
    [
        ("近三年净利润复合增速 > 20%", "近三年净利润复合增速"),
        ("经营现金流为正", "经营现金流"),
        ("EPS 大于 1", "EPS/每股收益"),
        ("PS 低于 2", "PS/市销率"),
        ("机构持仓增加", "机构持仓"),
        ("基金持仓增加", "机构持仓"),
        ("北向资金流入", "机构持仓"),
        ("研报评级买入", "研报评级/目标价"),
        ("目标价高于 50", "研报评级/目标价"),
        ("PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股", "近三年净利润复合增速"),
    ],
)
def test_unsupported_queries_preflight_without_ai_or_screen(db, seed_stocks, monkeypatch, query, label):
    _patch_no_ai(monkeypatch)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported query must not screen")),
    )

    response = strategy_selector.run_agent_selection(db, query, limit=10)

    assert response.plan.tool == "ask_clarification"
    assert response.plan.ai_used is False
    assert response.screen_result is None
    assert response.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert label in response.answer
    assert any(label in warning for warning in response.warnings)


@pytest.mark.parametrize("query", ["为什么这些股票排在前面", "查看第一只详情", "打开招商银行详情"])
def test_text_only_chat_operations_do_not_rescreen(db, seed_stocks, monkeypatch, query):
    _patch_no_ai(monkeypatch)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError(f"{query} must not screen")),
    )

    response = strategy_selector.run_chat_agent(db, query, context=LAST_RESULT_CONTEXT, limit=2)

    assert response.plan.tool in {"explain_result", "stock_detail"}
    assert response.plan.ai_used is False
    assert response.screen_result is None
    assert response.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    if response.plan.tool == "stock_detail":
        detail_call = next(call for call in response.tool_calls if call.name == "stock_detail")
        assert detail_call.result["url"] == "/detail/600036.SH"


def test_named_stock_detail_uses_model_judgment_without_screen(db, seed_stocks, monkeypatch):
    def model_detail(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="模型判断用户要看个股详情。",
            plan=AgentPlanResult(
                tool="stock_detail",
                tool_label="个股详情",
                reasoning="查看招商银行详情",
                extra={"name": "招商银行"},
            ),
        )

    _patch_react_decision(monkeypatch, model_detail)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stock_detail must not screen")),
    )

    response = agent_react.run_chat_react_agent(db, "我想看一下招商银行的详情", context={}, limit=2)

    assert response.plan.tool == "stock_detail"
    assert response.plan.ai_used is True
    assert response.screen_result is None
    assert response.tool_trace[0].startswith("ReAct step 1: 模型选择")
    detail_call = next(call for call in response.tool_calls if call.name == "stock_detail")
    assert detail_call.result["url"] == "/detail/600036.SH"


def test_model_stock_detail_unknown_extra_does_not_open_hallucinated_code(db, seed_stocks, monkeypatch):
    def model_detail(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="模型判断用户要看个股详情。",
            plan=AgentPlanResult(
                tool="stock_detail",
                tool_label="个股详情",
                reasoning="查看模型抽取的股票详情",
                extra={"code": "999999.SH", "name": "不存在公司"},
            ),
        )

    _patch_react_decision(monkeypatch, model_detail)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unknown stock_detail must not screen")),
    )

    response = agent_react.run_chat_react_agent(db, "看看这个", context={}, limit=2)

    assert response.plan.tool == "ask_clarification"
    assert response.plan.tool_label == "补充追问"
    assert response.plan.ai_used is True
    assert response.screen_result is None
    assert not any(call.name == "stock_detail" for call in response.tool_calls)
    assert "还没有定位到要查看的股票" in response.answer
    assert "未定位到有效详情目标" in response.tool_trace[0]


def test_chat_react_screen_uses_model_judgment(db, seed_stocks, monkeypatch):
    def model_screen(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="模型判断用户要执行股票筛选。",
            plan=AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="股息率和大盘股筛选",
                conditions=[
                    FilterCondition(field="dividend_yield", op="gt", value=5),
                    FilterCondition(field="market_cap", op="gt", value=500),
                ],
            ),
        )

    _patch_react_decision(monkeypatch, model_screen)

    response = agent_react.run_chat_react_agent(db, "股息率超过 5% 的大蓝筹", context={}, limit=10)

    assert response.plan.tool == "stock_screen"
    assert response.plan.ai_used is True
    assert response.screen_result is not None
    assert _condition_tuples(response) == [("dividend_yield", "gt", 5), ("market_cap", "gt", 500)]
    assert response.tool_trace[0].startswith("ReAct step 1: 模型选择")
    assert response.react_steps
    assert response.react_steps[-1]["type"] == "final"
    assert response.react_steps[-1]["fallback_reason"] is None


@pytest.mark.parametrize(
    ("query", "tool"),
    [
        ("为什么这些股票排在前面", "explain_result"),
        ("按股息率排序", "sort_results"),
        ("换一批", "paginate_results"),
    ],
)
def test_chat_react_context_operations_use_model_judgment(db, seed_stocks, monkeypatch, query, tool):
    def model_context(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason=f"模型判断使用 {tool}。",
            plan=AgentPlanResult(
                tool=tool,
                tool_label={
                    "explain_result": "结果解释",
                    "sort_results": "结果排序",
                    "paginate_results": "结果分页",
                }[tool],
                reasoning="基于上一轮结果处理",
                sort_by="dividend_yield" if tool == "sort_results" else None,
                offset=2 if tool == "paginate_results" else 0,
                limit=2,
            ),
        )

    _patch_react_decision(monkeypatch, model_context)

    response = agent_react.run_chat_react_agent(db, query, context=LAST_RESULT_CONTEXT, limit=2)

    assert response.plan.tool == tool
    assert response.plan.ai_used is True
    assert response.tool_trace[0].startswith("ReAct step 1: 模型选择")
    assert response.react_steps
    if tool == "explain_result":
        assert response.screen_result is None
        assert "不重新筛选" in response.answer
    else:
        assert response.screen_result is not None
        assert response.react_steps[-1]["fallback_reason"] is None


@pytest.mark.parametrize(
    ("query", "strategy_id"),
    [
        ("找最近强势突破的股票", "turtle_breakout"),
        ("找均线放量的股票", "ma_volume"),
    ],
)
def test_chat_react_known_strategy_intents_use_model_judgment(db, seed_stocks, monkeypatch, query, strategy_id):
    def model_strategy(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="action",
            public_reason="模型判断用户要执行内置策略。",
            plan=AgentPlanResult(
                tool="strategy_select",
                tool_label="策略选股",
                reasoning="选择内置策略",
                strategy_id=strategy_id,
                limit=5,
            ),
        )

    _patch_react_decision(monkeypatch, model_strategy)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("strategy intent must not call stock_screen")),
    )

    response = agent_react.run_chat_react_agent(db, query, context={}, limit=5)

    assert response.plan.tool == "strategy_select"
    assert response.plan.strategy_id == strategy_id
    assert response.plan.ai_used is True
    assert response.strategy_result is not None
    assert response.strategy_result.strategy.id == strategy_id
    assert response.screen_result is None
    assert response.tool_trace[0].startswith("ReAct step 1: 模型选择")
    assert response.react_steps[-1]["fallback_reason"] is None


@pytest.mark.parametrize("query", ["找一个我没定义过的神奇策略", "找短线强势机会"])
def test_chat_react_unknown_strategy_does_not_use_local_strategy(db, seed_stocks, monkeypatch, query):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "test unavailable"},
    )
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unknown strategy must not stock_screen")),
    )
    monkeypatch.setattr(
        strategy_selector,
        "run_strategy_selection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unknown strategy must not strategy_select")),
    )

    response = agent_react.run_chat_react_agent(db, query, context={}, limit=5)

    assert response.plan.tool == "ask_clarification"
    assert response.plan.ai_used is False
    assert response.plan.tool_label == "普通回复"
    assert response.screen_result is None
    assert response.strategy_result is None


@pytest.mark.parametrize(
    ("query", "expected_text"),
    [
        ("这个 Agent 是什么", "有界选股 Agent"),
        ("你好", "你好，我可以帮你"),
    ],
)
def test_chat_react_plain_chat_uses_model_final_without_tools(db, seed_stocks, monkeypatch, query, expected_text):
    def model_final(_query, context=None, observations=None, step_index=1):
        return AgentReactDecision(
            kind="final",
            public_reason="模型判断这是普通对话。",
            final_answer=expected_text,
        )

    _patch_react_decision(monkeypatch, model_final)
    monkeypatch.setattr(
        strategy_selector.screener_engine,
        "screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plain chat must not stock_screen")),
    )
    monkeypatch.setattr(
        strategy_selector,
        "run_strategy_selection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plain chat must not strategy_select")),
    )

    response = agent_react.run_chat_react_agent(db, query, context={}, limit=5)

    assert response.plan.tool == "ask_clarification"
    assert response.plan.tool_label == "普通回复"
    assert response.plan.ai_used is True
    assert expected_text in response.answer
    assert response.screen_result is None
    assert response.strategy_result is None
    assert [call.name for call in response.tool_calls] == ["tool_router"]
    assert response.react_steps[-1]["timing_phase"] == "model_final"
    assert response.react_steps[-1]["fallback_reason"] is None


@pytest.mark.parametrize(
    ("query", "tool", "offset"),
    [
        ("按股息率排序", "sort_results", 0),
        ("换一批", "paginate_results", 2),
        ("下一页", "paginate_results", 2),
    ],
)
def test_result_operations_reuse_previous_conditions(db, seed_stocks, monkeypatch, query, tool, offset):
    _patch_no_ai(monkeypatch)

    response = strategy_selector.plan_chat_agent(query, context=LAST_RESULT_CONTEXT, limit=2)

    assert response.plan.tool == tool
    assert response.plan.ai_used is False
    assert response.plan.offset == offset
    assert _condition_tuples(response) == [("pe", "lt", 15), ("pb", "lt", 2), ("industry", "in", ["银行"])]
    assert response.screen_result is None
    assert response.tool_trace[0] == "本地快速路径命中，跳过模型规划"

    screen_calls = []
    original_screen = strategy_selector.screener_engine.screen

    def spy_screen(db_arg, req):
        screen_calls.append(
            {
                "conditions": [(cond.field, cond.op, cond.value) for cond in req.conditions],
                "offset": req.offset,
                "limit": req.limit,
                "sort_by": req.sort_by,
            }
        )
        return original_screen(db_arg, req)

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", spy_screen)
    executed = strategy_selector.run_chat_agent(db, query, context=LAST_RESULT_CONTEXT, limit=2)

    assert executed.plan.tool == tool
    assert executed.screen_result is not None
    assert screen_calls
    assert screen_calls[0]["conditions"] == [("pe", "lt", 15), ("pb", "lt", 2), ("industry", "in", ["银行"])]
    assert screen_calls[0]["offset"] == offset
    assert screen_calls[0]["limit"] == 2
    if tool == "sort_results":
        assert screen_calls[0]["sort_by"] == "dividend_yield"


def test_non_deterministic_query_can_use_model_planner(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_status", lambda: {"configured": True, "ok": True, "reason": None})
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda _query, _context=None: AgentPlanResult(
            tool="stock_screen",
            tool_label="结构化股票筛选",
            reasoning="模型解析观察样本",
            conditions=[
                FilterCondition(field="industry", op="in", value=["银行"]),
                FilterCondition(field="pe", op="lt", value=15),
            ],
            sort_by="score",
            sort_desc=True,
        ),
    )

    response = strategy_selector.run_agent_selection(db, "请模型挑一个观察样本", limit=10)

    assert response.plan.tool == "stock_screen"
    assert response.plan.ai_used is True
    assert response.screen_result is not None
    assert response.tool_trace[0] == "模型 FC Agent 已选择工具并校验通过"


def test_bounded_react_model_path_and_timeout_metadata(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_status", lambda: {"configured": True, "ok": True, "reason": None})
    calls = []

    def model_step(query, context=None, observations=None, step_index=1):
        calls.append({"step_index": step_index, "observation_count": len(observations or [])})
        if observations:
            raise AssertionError("successful tool result should not request model final summary")
        return AgentReactDecision(
            kind="action",
            public_reason="模型选择银行筛选。",
            plan=AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="模型选择条件",
                conditions=[FilterCondition(field="industry", op="in", value=["银行"])],
            ),
        )

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", model_step)
    response = agent_react.run_chat_react_agent(db, "请模型做一次观察", context={}, limit=10)
    assert response.plan.ai_used is True
    assert any(step["type"] == "react_step" for step in response.react_steps)
    assert any(step["type"] == "final" and step["timing_phase"] == "local_final" for step in response.react_steps)
    assert calls == [{"step_index": 1, "observation_count": 0}]

    def slow_timeout(*_args, **_kwargs):
        time.sleep(0.02)
        return None

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_react_step", slow_timeout)
    monkeypatch.setattr(strategy_selector.qwen_client, "last_plan_failure_reason", lambda: "模型 ReAct 步骤超过 12 秒")
    fallback = agent_react.run_chat_react_agent(db, "找一个我没定义过的神奇策略", context={}, limit=10)
    final_event = fallback.react_steps[-1]
    assert fallback.plan.ai_used is False
    assert final_event["model_ms"] > 0
    assert "模型 ReAct 步骤超过 12 秒" in final_event["fallback_reason"]
