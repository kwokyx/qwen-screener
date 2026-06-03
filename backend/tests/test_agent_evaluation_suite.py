"""固定 Agent 评测集：锁住工具路由、上下文和误筛全市场风险。"""

import pytest

from app.services import strategy_selector


@pytest.fixture(autouse=True)
def force_local_agent(monkeypatch):
    """评测集默认使用本地规则，避免外部模型波动影响回归判断。"""
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "评测集固定使用本地规则"},
    )


def _assert_not_implicit_full_market(result):
    if result.plan.tool != "stock_screen":
        return
    assert result.plan.conditions or strategy_selector.is_explicit_all_stocks_query(result.query)


def test_eval_clear_screening_calls_stock_screen(db, seed_stocks):
    result = strategy_selector.run_agent_selection(db, "低估值银行", limit=10)

    assert result.plan.tool == "stock_screen"
    assert len(result.plan.conditions) == 3
    assert result.screen_result is not None
    assert result.screen_result.total == 1
    assert any(call.name == "stock_screen" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)


def test_eval_strategy_design_does_not_screen(db, seed_stocks):
    result = strategy_selector.run_agent_selection(db, "帮我设计一个稳健的选股策略，列出量化条件", limit=10)

    assert result.plan.tool == "strategy_design"
    assert len(result.plan.conditions) >= 5
    assert result.screen_result is None
    assert result.strategy_result is None
    assert "tool_router -> strategy_design" in result.tool_trace
    assert not any(call.name == "stock_screen" for call in result.tool_calls)
    assert "先不执行筛选" in result.answer


def test_eval_confirmation_without_context_never_screens_all_market(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("无上下文确认语不应调用筛选工具")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    result = strategy_selector.run_chat_agent(db, "可以，做吧", context={}, limit=10)

    assert result.plan.tool == "ask_clarification"
    assert result.screen_result is None
    assert len(result.plan.conditions) == 0
    assert "还没有可以直接执行的上一轮条件" in result.answer
    _assert_not_implicit_full_market(result)


def test_eval_confirmation_with_context_executes_previous_conditions(db, seed_stocks):
    context = {
        "last_plan": {"tool": "strategy_design", "logic": "AND", "sort_by": "roe", "sort_desc": True},
        "last_conditions": [
            {"field": "pe", "op": "lt", "value": 20},
            {"field": "roe", "op": "gt", "value": 20},
        ],
    }

    result = strategy_selector.run_chat_agent(db, "现在执行", context=context, limit=10)

    assert result.plan.tool == "stock_screen"
    assert result.plan.sort_by == "roe"
    assert len(result.plan.conditions) == 2
    assert result.screen_result is not None
    assert {item.code for item in result.screen_result.items} == {"000333.SZ", "000596.SZ"}
    assert any(call.name == "stock_screen" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)


def test_eval_next_page_preserves_context_and_moves_offset(db, seed_stocks):
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "score", "sort_desc": True},
        "last_conditions": [{"field": "pe", "op": "lt", "value": 500}],
        "last_result": {
            "total": 5,
            "offset": 0,
            "limit": 2,
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 500}],
        },
    }

    result = strategy_selector.run_chat_agent(db, "换一批", context=context, limit=2)

    assert result.plan.tool == "stock_screen"
    assert result.plan.offset == 2
    assert result.screen_result is not None
    assert result.screen_result.offset == 2
    assert any(call.name == "result_sort" and call.label == "结果分页" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)


def test_eval_explain_previous_result_uses_context_without_rescreen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("解释上一轮结果不应重新筛选")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    context = {
        "last_plan": {"tool": "stock_screen", "sort_by": "roe", "sort_desc": True},
        "last_result": {
            "total": 2,
            "items": [
                {"code": "600036.SH", "name": "招商银行", "industry": "银行", "pe": 6.5, "roe": 16.5},
                {"code": "000333.SZ", "name": "美的集团", "industry": "白色家电", "pe": 13.5, "roe": 22.0},
            ],
            "parsed_conditions": [
                {"field": "pe", "op": "lt", "value": 15},
                {"field": "roe", "op": "gt", "value": 15},
            ],
        },
    }

    result = strategy_selector.run_chat_agent(db, "为什么这些股票排在前面？", context=context, limit=10)

    assert result.plan.tool == "explain_result"
    assert result.screen_result is None
    assert result.strategy_result is None
    assert "排序依据：按ROE从高到低排列" in result.answer
    assert "条件对应关系：" in result.answer
    assert "可能风险点：" in result.answer
    assert "招商银行" in result.answer
    assert any(call.name == "explain_result" for call in result.tool_calls)


def test_eval_vague_question_asks_for_clarification(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("模糊请求必须先追问，不应筛选")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    result = strategy_selector.run_agent_selection(db, "帮我选点好股票", limit=10)

    assert result.plan.tool == "ask_clarification"
    assert result.screen_result is None
    assert len(result.plan.conditions) == 0
    assert "我先不筛股票" in result.answer


@pytest.mark.parametrize("query", ["你好", "谢谢", "随便聊聊"])
def test_eval_smalltalk_never_screens_market(db, seed_stocks, query, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("闲聊语不应调用筛选工具")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    result = strategy_selector.run_agent_selection(db, query, limit=10)

    assert result.plan.tool == "ask_clarification"
    assert result.screen_result is None
    assert len(result.plan.conditions) == 0
    _assert_not_implicit_full_market(result)


def test_eval_explicit_all_market_is_allowed(db, seed_stocks):
    result = strategy_selector.run_agent_selection(db, "显示全市场股票", limit=10)

    assert result.plan.tool == "stock_screen"
    assert len(result.plan.conditions) == 0
    assert result.screen_result is not None
    assert result.screen_result.total >= 1
    assert any(call.name == "stock_screen" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)


def test_eval_sort_request_reuses_previous_conditions(db, seed_stocks):
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND"},
        "last_conditions": [{"field": "pe", "op": "lt", "value": 500}],
    }

    result = strategy_selector.run_chat_agent(db, "按股息率排序", context=context, limit=10)

    assert result.plan.tool == "stock_screen"
    assert result.plan.sort_by == "dividend_yield"
    assert result.plan.sort_desc is True
    assert len(result.plan.conditions) == 1
    assert result.screen_result is not None
    assert any(call.name == "result_sort" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("再严格一点", [("pe", "lt", 16), ("roe", "gt", 23)]),
        ("放宽一点", [("pe", "lt", 25), ("roe", "gt", 17)]),
    ],
)
def test_eval_tighten_and_relax_reuse_previous_conditions(db, seed_stocks, query, expected):
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "roe", "sort_desc": True},
        "last_conditions": [
            {"field": "pe", "op": "lt", "value": 20},
            {"field": "roe", "op": "gt", "value": 20},
        ],
    }

    result = strategy_selector.run_chat_agent(db, query, context=context, limit=10)

    assert result.plan.tool == "stock_screen"
    assert [(c.field, c.op, c.value) for c in result.plan.conditions] == expected
    assert result.screen_result is not None
    assert any(call.name == "condition_parser" for call in result.tool_calls)
    _assert_not_implicit_full_market(result)
