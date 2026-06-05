from app.schemas.screener import FilterCondition, ScreenRequest
from app.schemas.strategy import StrategyAgentPlan, StrategyAgentResponse
from app.services import strategy_selector
from app.services.qwen_client.agent_planner import AgentPlanResult


def test_agent_design_request_does_not_execute_screen(db, seed_stocks, monkeypatch):
    def fail_parse(_query):
        raise AssertionError("design-only request should not parse filters")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )
    monkeypatch.setattr(strategy_selector.qwen_client, "parse_nl_query", fail_parse)

    res = strategy_selector.run_agent_selection(db, "帮我设计一个稳健的选股策略，列出量化条件", limit=10)

    assert res.plan.tool == "strategy_design"
    assert res.plan.tool_label == "策略设计"
    assert res.screen_result is None
    assert res.strategy_result is None
    assert res.plan.condition_labels == [
        "ROE不低于15",
        "资产负债率不高于60",
        "毛利率不低于25",
        "净利润同比不低于10",
        "市盈率介于0、25",
        "市净率介于0、3",
        "总市值不低于100",
    ]
    assert res.tool_trace == [
        "tool_router -> strategy_design",
        "跳过 screener_engine.screen：当前请求是策略设计，不是执行选股",
    ]
    assert "先不执行筛选" in res.answer
    assert "命中 0 只" not in res.answer


def test_agent_clarifies_vague_query(db, seed_stocks, monkeypatch):
    def fail_parse(_query):
        raise AssertionError("vague query should not parse filters")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )
    monkeypatch.setattr(strategy_selector.qwen_client, "parse_nl_query", fail_parse)

    res = strategy_selector.run_agent_selection(db, "帮我选点好股票", limit=10)

    assert res.plan.tool == "ask_clarification"
    assert res.screen_result is None
    assert res.strategy_result is None
    assert "我先不筛股票" in res.answer
    assert "未调用 screener_engine.screen" in res.tool_trace[1]


def test_chat_agent_explains_previous_result_without_rescreen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("explain_result should not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    context = {
        "last_result": {
            "total": 1,
            "items": [
                {"code": "600036.SH", "name": "招商银行", "industry": "银行", "pe": 6.5, "roe": 16.5}
            ],
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
        }
    }

    res = strategy_selector.run_chat_agent(db, "为什么这些股票会被选出来？", context=context, limit=10)

    assert res.plan.tool == "explain_result"
    assert res.screen_result is None
    assert res.strategy_result is None
    assert "招商银行" in res.answer


def test_chat_agent_asks_when_explain_has_no_previous_result(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("missing-context explanation should not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_chat_agent(db, "为什么这些股票会被选出来？", context={}, limit=10)

    assert res.plan.tool == "ask_clarification"
    assert res.screen_result is None
    assert "还没有可解释的上一轮股票结果" in res.answer


def test_chat_agent_asks_when_confirmation_has_no_previous_conditions(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("confirmation without context should not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_chat_agent(db, "可以，做吧", context={}, limit=10)

    assert res.plan.tool == "ask_clarification"
    assert res.screen_result is None
    assert "还没有可以直接执行的上一轮条件" in res.answer


def test_chat_agent_design_with_deferred_execution_does_not_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("strategy design should not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_chat_agent(db, "帮我设计一个稳健的选股策略，先别执行", context={}, limit=10)

    assert res.plan.tool == "strategy_design"
    assert res.screen_result is None
    assert res.plan.conditions
    assert "先不执行筛选" in res.answer


def test_strategy_design_fast_path_skips_model_when_ai_available(db, seed_stocks, monkeypatch):
    def fail_plan(*_args, **_kwargs):
        raise AssertionError("explicit strategy design should not call model planner")

    def fail_screen(*_args, **_kwargs):
        raise AssertionError("strategy design should not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_plan)
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_agent_selection(db, "帮我设计一个稳健的选股策略，先别执行", limit=10)

    assert res.plan.tool == "strategy_design"
    assert res.screen_result is None
    assert res.plan.ai_configured is True
    assert res.plan.ai_used is False


def test_local_fast_paths_skip_ai_health_probe(db, seed_stocks, monkeypatch):
    def fail_status():
        raise AssertionError("local fast-path should not probe AI health")

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("local fast-path should not call model planner")

    def fail_screen(*_args, **_kwargs):
        raise AssertionError("non-executing fast-path should not screen")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(strategy_selector, "_ai_status", fail_status)
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_plan)
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    cases = {
        "你好": "ask_clarification",
        "可以，做吧": "ask_clarification",
        "为什么这些股票排在前面": "ask_clarification",
        "查看第一只详情": "ask_clarification",
        "帮我设计一个稳健的选股策略，先别执行": "strategy_design",
    }
    for query, expected_tool in cases.items():
        res = strategy_selector.run_agent_selection(db, query, limit=10)
        assert res.plan.tool == expected_tool
        assert res.screen_result is None
        assert res.plan.ai_configured is True
        assert res.plan.ai_used is False


def test_chat_agent_executes_previous_design_conditions_after_confirmation(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    context = {
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
    }

    res = strategy_selector.run_chat_agent(db, "现在执行", context=context, limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_used is False
    assert res.plan.sort_by == "roe"
    assert res.screen_result is not None
    assert {item.code for item in res.screen_result.items} == {"000333.SZ", "000596.SZ"}
    assert "沿用上一轮结构化条件" in res.tool_trace
    assert "上一轮策略条件" in res.answer
    assert any(call.name == "stock_screen" and call.result["total"] == 2 for call in res.tool_calls)


def test_chat_agent_fast_path_skips_model_for_confirmation_when_available(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def plan_agent_turn(query, context=None):
        raise AssertionError("confirmation fast-path should not call the model")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", plan_agent_turn)
    context = {
        "last_plan": {"tool": "strategy_design", "logic": "AND"},
        "last_conditions": [
            {"field": "pe", "op": "lt", "value": 20},
            {"field": "roe", "op": "gt", "value": 20},
        ],
    }

    res = strategy_selector.run_chat_agent(db, "可以，做吧", context=context, limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_used is False
    assert res.screen_result is not None
    assert {item.code for item in res.screen_result.items} == {"000333.SZ", "000596.SZ"}
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"


def test_chat_agent_fast_path_skips_model_for_obvious_local_intents(monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )

    def fail_plan(_query, _context=None):
        raise AssertionError("obvious local intents should not call the model")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_plan)
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "roe", "sort_desc": True},
        "last_conditions": [{"field": "pe", "op": "lt", "value": 20}],
        "last_result": {
            "total": 1,
            "items": [{"code": "600036.SH", "name": "招商银行", "pe": 6.5, "roe": 16.5}],
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 20}],
        },
    }

    cases = [
        ("你好", {}, "ask_clarification"),
        ("可以，做吧", context, "stock_screen"),
        ("查看第一只详情", context, "stock_detail"),
        ("为什么这些股票排在前面", context, "explain_result"),
    ]

    for query, ctx, expected_tool in cases:
        res = strategy_selector.plan_chat_agent(query, context=ctx, limit=10)
        assert res.plan.tool == expected_tool
        assert res.plan.ai_used is False
        assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"


def test_chat_agent_uses_model_strategy_design_copy(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("strategy_design should not execute screen")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda _query, _context=None: AgentPlanResult(
            tool="strategy_design",
            tool_label="策略设计",
            reasoning="AI 先设计策略",
            extra={
                "quantitative_conditions": ["ROE 不低于 18%", "PE 低于 20"],
                "framework": "质量与估值并重",
                "notes": "按行业调整阈值",
            },
        ),
    )

    res = strategy_selector.run_chat_agent(db, "帮我设计一个稳健策略", context={}, limit=10)

    assert res.plan.tool == "strategy_design"
    assert res.plan.ai_used is True
    assert res.screen_result is None
    assert "ROE 不低于 18%" in res.answer
    assert "质量与估值并重" in res.answer
    assert "按行业调整阈值" in res.answer


def test_chat_agent_tightens_previous_conditions(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "roe", "sort_desc": True},
        "last_conditions": [
            {"field": "pe", "op": "lt", "value": 20},
            {"field": "roe", "op": "gt", "value": 20},
        ],
    }

    res = strategy_selector.run_chat_agent(db, "再严格一点", context=context, limit=10)

    assert res.plan.tool == "stock_screen"
    assert [(c.field, c.op, c.value) for c in res.plan.conditions] == [
        ("pe", "lt", 16),
        ("roe", "gt", 23),
    ]
    assert res.screen_result is not None
    assert any(call.name == "condition_parser" and call.params["mode"] == "收紧" for call in res.tool_calls)


def test_chat_agent_relaxes_previous_conditions(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "roe", "sort_desc": True},
        "last_conditions": [
            {"field": "pe", "op": "lt", "value": 20},
            {"field": "roe", "op": "gt", "value": 20},
        ],
    }

    res = strategy_selector.run_chat_agent(db, "放宽一点", context=context, limit=10)

    assert res.plan.tool == "stock_screen"
    assert [(c.field, c.op, c.value) for c in res.plan.conditions] == [
        ("pe", "lt", 25),
        ("roe", "gt", 17),
    ]
    assert res.screen_result is not None


def test_chat_agent_sorts_previous_conditions(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND"},
        "last_conditions": [{"field": "pe", "op": "lt", "value": 500}],
    }

    res = strategy_selector.run_chat_agent(db, "按股息率排序", context=context, limit=10)

    assert res.plan.tool == "sort_results"
    assert res.plan.sort_by == "dividend_yield"
    assert res.plan.sort_desc is True
    assert res.screen_result is not None
    assert any(call.name == "result_sort" for call in res.tool_calls)


def test_chat_agent_next_page_uses_previous_offset(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
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

    res = strategy_selector.run_chat_agent(db, "换一批", context=context, limit=2)

    assert res.plan.tool == "paginate_results"
    assert res.plan.offset == 2
    assert res.screen_result is not None
    assert res.screen_result.offset == 2
    assert "下一批结果" in res.answer
    assert "转换为" not in res.answer
    assert any(call.name == "result_sort" and call.label == "结果分页" for call in res.tool_calls)


def test_chat_agent_next_page_rolls_over_when_past_end(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    context = {
        "last_plan": {"tool": "stock_screen", "logic": "AND", "sort_by": "score", "sort_desc": True},
        "last_conditions": [{"field": "pe", "op": "lt", "value": 500}],
        "last_result": {
            "total": 5,
            "offset": 4,
            "limit": 2,
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 500}],
        },
    }

    res = strategy_selector.run_chat_agent(db, "换一批", context=context, limit=2)

    assert res.plan.tool == "paginate_results"
    assert res.plan.offset == 0
    assert res.screen_result is not None
    assert res.screen_result.offset == 0
    assert res.screen_result.items
    assert "已回到第一批结果" in res.answer
    assert any(call.name == "result_pagination_reset" for call in res.tool_calls)


def test_next_page_summary_handles_past_end():
    plan = StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="翻页测试",
        offset=50,
        limit=50,
    )

    answer = strategy_selector._summarize_screen_agent("换一批", plan, total=42, names=[])

    assert "没有更多结果" in answer
    assert "51–42" not in answer


def test_chat_agent_adjustment_without_context_asks_first(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("adjustment without context must not execute screen")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_chat_agent(db, "再严格一点", context={}, limit=10)

    assert res.plan.tool == "ask_clarification"
    assert res.screen_result is None
    assert "没有上一轮条件" in res.answer


def test_agent_uses_model_planner_then_executes_local_screen(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda _query, _context=None: AgentPlanResult(
            tool="stock_screen",
            tool_label="结构化股票筛选",
            reasoning="AI 解析测试",
            conditions=[
                FilterCondition(field="industry", op="in", value=["半导体"]),
                FilterCondition(field="market_cap", op="gt", value=500),
            ],
            sort_by="market_cap",
            sort_desc=True,
        ),
    )

    res = strategy_selector.run_agent_selection(db, "请模型挑一个观察样本", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_used is True
    assert res.plan.condition_labels == ["行业包含半导体", "总市值大于500"]
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.screen_result.items[0].code == "688981.SH"
    assert res.tool_trace == ["模型 FC Agent 已选择工具并校验通过", "调用 screener_engine.screen(conditions=2, limit=10)"]
    assert "中芯国际" in res.answer


def test_agent_local_fast_path_skips_model_even_when_available(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("deterministic screen should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("deterministic screen should not call model")),
    )

    res = strategy_selector.run_agent_selection(db, "低估值银行", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_used is False
    assert res.plan.ai_configured is True
    assert res.plan.condition_labels == ["市盈率低于15", "市净率低于2", "行业包含银行"]
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert res.warnings == []


def test_agent_local_fast_path_preserves_explicit_roe_and_profit_growth(db, seed_stocks, monkeypatch):
    def fail_ai_status():
        raise AssertionError("deterministic screen should not probe AI health")

    def fail_model(*_args, **_kwargs):
        raise AssertionError("deterministic screen should not call the model")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(strategy_selector, "_ai_status", fail_ai_status)
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_model)

    res = strategy_selector.plan_agent_selection(
        "ROE 大于 15 且最新季度净利润同比正增长的成长股",
        limit=10,
    )

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_used is False
    assert [(cond.field, cond.op, cond.value) for cond in res.plan.conditions] == [
        ("roe", "gt", 15),
        ("profit_yoy", "gt", 0),
    ]
    assert "营收同比大于20" not in res.plan.condition_labels
    assert "净利润同比大于20" not in res.plan.condition_labels
    assert res.plan.ai_configured is True
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert res.warnings == []


def test_agent_local_fast_path_executes_supported_screen_queries(db, seed_stocks, monkeypatch):
    def fail_ai_status():
        raise AssertionError("deterministic screen should not probe AI health")

    def fail_model(*_args, **_kwargs):
        raise AssertionError("deterministic screen should not call the model")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(strategy_selector, "_ai_status", fail_ai_status)
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_model)

    cases = [
        (
            "ROE 大于 15 且最新季度净利润同比正增长的成长股",
            [("roe", "gt", 15), ("profit_yoy", "gt", 0)],
        ),
        (
            "低估值高分红的银行股",
            [("pe", "lt", 15), ("pb", "lt", 2), ("dividend_yield", "gt", 3), ("industry", "in", ["银行"])],
        ),
        (
            "PE 低于 15 且 PB 小于 2 的银行股",
            [("pe", "lt", 15), ("pb", "lt", 2), ("industry", "in", ["银行"])],
        ),
    ]

    for query, expected_conditions in cases:
        res = strategy_selector.run_agent_selection(db, query, limit=10)
        assert res.plan.tool == "stock_screen"
        assert res.plan.ai_configured is True
        assert res.plan.ai_used is False
        assert res.screen_result is not None
        assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
        assert [(cond.field, cond.op, cond.value) for cond in res.plan.conditions] == expected_conditions


def test_agent_fallback_reports_model_timeout_reason(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": True, "reason": None},
    )
    monkeypatch.setattr(strategy_selector.qwen_client, "reset_plan_failure_reason", lambda: None)
    monkeypatch.setattr(strategy_selector.qwen_client, "last_plan_failure_reason", lambda: "模型规划超过 10 秒")
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", lambda _query, _context=None: None)

    res = strategy_selector.plan_agent_selection("找最近强势突破的股票", limit=10)

    assert res.plan.tool == "strategy_select"
    assert res.plan.ai_used is False
    assert "模型规划超过 10 秒，已使用本地规则兜底" in res.warnings[0]


def test_agent_preflights_unsupported_profit_cagr_without_ai_or_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("unsupported metrics must not execute a partial screen")

    def fail_ai_status():
        raise AssertionError("unsupported preflight should not probe AI health")

    def fail_model(*_args, **_kwargs):
        raise AssertionError("unsupported preflight should not call the model")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(strategy_selector, "_ai_status", fail_ai_status)
    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_model)
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.run_agent_selection(
        db,
        "找出 PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股",
        limit=10,
    )

    assert res.plan.tool == "ask_clarification"
    assert res.plan.conditions == []
    assert res.screen_result is None
    assert res.plan.ai_configured is True
    assert res.plan.ai_used is False
    assert "近三年净利润复合增速" in res.answer
    assert "本轮没有执行筛选" in res.answer
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert any("当前数据字段不支持：近三年净利润复合增速" in warning for warning in res.warnings)


def test_agent_blocks_unsupported_metric_families_without_partial_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("unsupported metric queries must not execute a partial screen")

    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("unsupported preflight should not probe AI health")),
    )
    monkeypatch.setattr(
        strategy_selector.qwen_client,
        "plan_agent_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported preflight should not call the model")),
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    cases = [
        ("找 PE 低于 15、扣非净利润同比增长的消费股", "扣非净利润"),
        ("找 PE 低于 15、经营现金流为正的消费股", "经营现金流"),
        ("找 EPS 大于 1 的消费股", "EPS/每股收益"),
        ("找 PS 低于 2 的消费股", "PS/市销率"),
        ("找机构持仓增加的消费股", "机构持仓"),
        ("找基金持仓增加的消费股", "机构持仓"),
        ("找北向资金持续流入的消费股", "机构持仓"),
        ("找研报评级买入的消费股", "研报评级/目标价"),
        ("找目标价高于 50 的消费股", "研报评级/目标价"),
    ]

    for query, label in cases:
        res = strategy_selector.run_agent_selection(db, query, limit=10)
        assert res.plan.tool == "ask_clarification"
        assert res.plan.conditions == []
        assert res.screen_result is None
        assert res.plan.ai_configured is True
        assert res.plan.ai_used is False
        assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
        assert label in res.answer
        assert any(f"当前数据字段不支持：{label}" in warning for warning in res.warnings)


def test_agent_supported_metrics_still_plan_normal_screen(monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.plan_agent_selection(
        "ROE 大于 15 且最新季度净利润同比正增长的成长股",
        limit=10,
    )

    assert res.plan.tool == "stock_screen"
    assert [(cond.field, cond.op, cond.value) for cond in res.plan.conditions] == [
        ("roe", "gt", 15),
        ("profit_yoy", "gt", 0),
    ]
    assert not any("当前数据字段不支持" in warning for warning in res.warnings)


def test_agent_local_growth_template_only_applies_without_explicit_metrics(monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.plan_agent_selection("成长股", limit=10)

    assert res.plan.tool == "stock_screen"
    assert [(cond.field, cond.op, cond.value) for cond in res.plan.conditions] == [
        ("revenue_yoy", "gt", 20),
        ("profit_yoy", "gt", 20),
    ]


def test_agent_allows_explicit_all_stocks_query(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.run_agent_selection(db, "查看全部股票", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.conditions == []
    assert res.screen_result is not None
    assert res.screen_result.total == 5


def test_agent_execution_guard_blocks_implicit_empty_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("implicit empty screen must be blocked before execution")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    response = StrategyAgentResponse(
        query="可以，做吧",
        plan=StrategyAgentPlan(
            tool="stock_screen",
            tool_label="结构化股票筛选",
            reasoning="test malformed plan",
            conditions=[],
        ),
        answer="等待执行",
    )

    result = strategy_selector.execute_agent_plan(db, response, limit=10)

    assert result.plan.tool == "ask_clarification"
    assert result.screen_result is None
    assert any("已阻止无条件全市场筛选" in warning for warning in result.warnings)


def test_agent_does_not_apply_hidden_default_conditions(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("ambiguous query should ask before screening")

    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )
    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    result = strategy_selector.run_agent_selection(db, "随便看看", limit=10)

    assert result.plan.tool == "ask_clarification"
    assert result.screen_result is None
    assert any("已阻止无条件全市场筛选" in warning for warning in result.warnings)


def test_agent_planning_does_not_execute_screen(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    def fail_screen(*_args, **_kwargs):
        raise AssertionError("planning must not execute screener_engine.screen")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)

    res = strategy_selector.plan_agent_selection("低估值银行", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.condition_labels == ["市盈率低于15", "市净率低于2", "行业包含银行"]
    assert res.screen_result is None
    assert res.strategy_result is None


def test_agent_clear_supported_screen_skips_ai_health_when_ai_unavailable(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: True)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("deterministic screen should not probe AI health")),
    )

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("deterministic screen should not call the model")

    monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_plan)

    res = strategy_selector.run_agent_selection(db, "半导体行业里的大市值龙头", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_configured is True
    assert res.plan.ai_used is False
    assert res.plan.condition_labels == ["总市值大于500", "行业包含半导体"]
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.screen_result.items[0].code == "688981.SH"
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert res.warnings == []


def test_agent_clear_supported_screen_runs_without_configured_ai(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(strategy_selector, "_ai_configured", lambda: False)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: (_ for _ in ()).throw(AssertionError("deterministic screen should not probe AI health")),
    )

    res = strategy_selector.run_agent_selection(db, "低估值银行", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_configured is False
    assert res.plan.ai_used is False
    assert "市盈率低于15" in res.plan.condition_labels
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.screen_result.items[0].code == "600036.SH"
    assert res.tool_trace[0] == "本地快速路径命中，跳过模型规划"
    assert res.warnings == []


def test_agent_routes_breakout_query_to_strategy_tool(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "模型不可用: test-model"},
    )

    res = strategy_selector.run_agent_selection(db, "找最近强势突破的股票", limit=5)

    assert res.plan.tool == "strategy_select"
    assert res.plan.strategy_id == "turtle_breakout"
    assert res.strategy_result is not None
    assert res.strategy_result.strategy.id == "turtle_breakout"
    assert res.tool_trace == [
        "调用 strategy_selector.run_strategy_selection(strategy_id=turtle_breakout, limit=5)",
    ]


def test_agent_routes_limit_up_shakeout_query_to_strategy_tool(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "模型不可用: test-model"},
    )

    res = strategy_selector.run_agent_selection(db, "找涨停后承接的股票", limit=5)

    assert res.plan.tool == "strategy_select"
    assert res.plan.strategy_id == "limit_up_shakeout"
    assert res.strategy_result is not None
    assert res.strategy_result.strategy.id == "limit_up_shakeout"


def test_agent_routes_uptrend_limit_down_query_to_strategy_tool(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "模型不可用: test-model"},
    )

    res = strategy_selector.run_agent_selection(db, "找上升趋势急跌的股票", limit=5)

    assert res.plan.tool == "strategy_select"
    assert res.plan.strategy_id == "uptrend_limit_down"
    assert res.strategy_result is not None
    assert res.strategy_result.strategy.id == "uptrend_limit_down"


def test_list_agent_tools_documents_screen_fields():
    tools = strategy_selector.list_agent_tools()
    by_id = {tool.id: tool for tool in tools}

    assert {
        "strategy_design", "stock_screen", "industry_match", "result_sort",
        "strategy_select", "explain_result", "stock_detail", "ask_clarification",
    } <= set(by_id)
    assert "不调用 screener_engine" in " ".join(by_id["strategy_design"].data_notes)
    assert by_id["stock_screen"].fields
    assert any(field.key == "pe" and field.label == "市盈率" for field in by_id["stock_screen"].fields)
    assert "字段缺失" in " ".join(by_id["stock_screen"].data_notes)
    assert "行业条件" in " ".join(by_id["industry_match"].data_notes)
    assert "分页前执行" in " ".join(by_id["result_sort"].data_notes)
    assert "收益回测" in " ".join(by_id["strategy_select"].data_notes)
    assert "上一轮结果" in by_id["explain_result"].description
    assert "不会调用 screener_engine" in " ".join(by_id["stock_detail"].data_notes)
    assert "不调用 screener_engine" in " ".join(by_id["ask_clarification"].data_notes)


def test_chat_agent_stock_detail_from_previous_result_without_screen(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("stock_detail must not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "测试强制使用本地规则"},
    )

    context = {
        "last_result": {
            "items": [
                {"code": "600036.SH", "name": "招商银行"},
                {"code": "688981.SH", "name": "中芯国际"},
            ],
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
        }
    }

    res = strategy_selector.run_chat_agent(db, "查看第一只详情", context=context, limit=10)

    assert res.plan.tool == "stock_detail"
    assert res.screen_result is None
    detail_call = next(call for call in res.tool_calls if call.name == "stock_detail")
    assert detail_call.result == {
        "code": "600036.SH",
        "name": "招商银行",
        "url": "/detail/600036.SH",
    }
    assert "未重新筛选" in " ".join(res.tool_trace)


def test_chat_agent_stock_detail_by_code_without_context(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("stock_detail by code must not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.run_chat_agent(db, "查看 600036.SH 详情", context={}, limit=10)

    assert res.plan.tool == "stock_detail"
    assert res.screen_result is None
    detail_call = next(call for call in res.tool_calls if call.name == "stock_detail")
    assert detail_call.result["code"] == "600036.SH"


def test_chat_agent_stock_detail_supports_bj_code(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("stock_detail by BJ code must not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.run_chat_agent(db, "查看 920111.BJ 详情", context={}, limit=10)

    assert res.plan.tool == "stock_detail"
    detail_call = next(call for call in res.tool_calls if call.name == "stock_detail")
    assert detail_call.result["code"] == "920111.BJ"


def test_chat_agent_stock_detail_without_target_asks_clarification(db, seed_stocks, monkeypatch):
    def fail_screen(*_args, **_kwargs):
        raise AssertionError("missing detail target must not execute screening")

    monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.run_chat_agent(db, "打开股票详情", context={}, limit=10)

    assert res.plan.tool == "ask_clarification"
    assert res.screen_result is None
    assert "还没有定位到要查看的股票" in res.answer


# ---------------------------------------------------------------------------
# Model FC Agent planner integration tests
# ---------------------------------------------------------------------------

class TestModelPlannerIntegration:
    """Tests for model-first routing via plan_agent_turn in plan_agent_selection."""

    def test_model_chooses_strategy_design_does_not_screen(self, db, seed_stocks, monkeypatch):
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="strategy_design",
                tool_label="策略设计",
                reasoning="设计请求",
                extra={"quantitative_conditions": ["ROE>15", "PE<25"]},
            ),
        )

        res = strategy_selector.run_agent_selection(db, "帮我设计一个稳健的选股策略", limit=10)

        assert res.plan.tool == "strategy_design"
        assert res.plan.ai_used is True
        assert res.screen_result is None
        assert res.strategy_result is None

    def test_model_chooses_strategy_select_executes_strategy(self, db, seed_stocks, monkeypatch):
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="strategy_select",
                tool_label="策略选股",
                reasoning="突破策略",
                strategy_id="turtle_breakout",
                limit=10,
            ),
        )

        res = strategy_selector.run_agent_selection(db, "找最近强势突破的股票", limit=10)

        assert res.plan.tool == "strategy_select"
        assert res.plan.ai_used is True
        assert res.plan.strategy_id == "turtle_breakout"
        assert res.strategy_result is not None

    def test_model_explain_without_context_downgrades_to_clarification(self, db, seed_stocks, monkeypatch):
        def fail_screen(*_args, **_kwargs):
            raise AssertionError("explain_result should not execute screen")

        monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="explain_result",
                tool_label="结果解释",
                reasoning="解释上一轮",
            ),
        )

        res = strategy_selector.run_agent_selection(db, "为什么这些股票会被选出来？", limit=10)

        assert res.plan.tool == "ask_clarification"
        assert res.plan.ai_used is True
        assert res.screen_result is None
        assert "还没有可解释的上一轮股票结果" in res.answer

    def test_model_chooses_ask_clarification_does_not_screen(self, db, seed_stocks, monkeypatch):
        def fail_screen(*_args, **_kwargs):
            raise AssertionError("ask_clarification should not execute screen")

        monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="ask_clarification",
                tool_label="补充追问",
                reasoning="需求模糊",
            ),
        )

        res = strategy_selector.run_agent_selection(db, "帮我选点好股票", limit=10)

        assert res.plan.tool == "ask_clarification"
        assert res.plan.ai_used is True
        assert res.screen_result is None
        assert res.strategy_result is None
        assert "我先不筛股票" in res.answer

    def test_model_chooses_stock_detail_does_not_screen(self, db, seed_stocks, monkeypatch):
        def fail_screen(*_args, **_kwargs):
            raise AssertionError("stock_detail should not execute screen")

        monkeypatch.setattr(strategy_selector.screener_engine, "screen", fail_screen)
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="stock_detail",
                tool_label="个股详情",
                reasoning="查看详情",
                extra={"name": "招商银行"},
            ),
        )
        context = {
            "last_result": {
                "items": [
                    {"code": "600036.SH", "name": "招商银行"},
                    {"code": "688981.SH", "name": "中芯国际"},
                ],
                "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
            }
        }

        res = strategy_selector.plan_agent_selection("打开招商银行详情", context=context, limit=10)

        assert res.plan.tool == "stock_detail"
        assert res.plan.ai_used is True
        assert res.screen_result is None
        detail_call = next(call for call in res.tool_calls if call.name == "stock_detail")
        assert detail_call.result["url"] == "/detail/600036.SH"

    def test_model_fallback_on_invalid_tool_name(self, db, seed_stocks, monkeypatch):
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: None,  # simulate failure
        )

        res = strategy_selector.run_agent_selection(db, "找最近强势突破的股票", limit=10)

        assert res.plan.tool == "strategy_select"
        assert res.plan.ai_used is False
        assert "模型未生成有效规划" in res.warnings[0]
        assert res.strategy_result is not None

    def test_model_fallback_when_unavailable(self, db, seed_stocks, monkeypatch):
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": False, "reason": "模型不可用: test"},
        )

        def fail_plan(_query, _context=None):
            raise AssertionError("plan_agent_turn should not be called when AI unavailable")

        monkeypatch.setattr(strategy_selector.qwen_client, "plan_agent_turn", fail_plan)

        res = strategy_selector.run_agent_selection(db, "找最近强势突破的股票", limit=10)

        assert res.plan.tool == "strategy_select"
        assert res.plan.ai_used is False
        assert res.strategy_result is not None
        assert "AI 服务已配置但当前不可用" in res.warnings[0]

    def test_model_allows_explicit_all_stocks_empty_conditions(self, db, seed_stocks, monkeypatch):
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="全市场查询",
                conditions=[],
                sort_by="market_cap",
                sort_desc=True,
            ),
        )

        res = strategy_selector.run_agent_selection(db, "查看全市场股票", limit=10)

        assert res.plan.tool == "stock_screen"
        assert res.plan.ai_used is True
        assert res.plan.conditions == []
        assert res.screen_result is not None
        assert res.screen_result.total == 5

    def test_model_blocked_implicit_empty_conditions(self, db, seed_stocks, monkeypatch):
        """Model returns empty conditions for non-explicit query → guard blocks."""
        monkeypatch.setattr(
            strategy_selector,
            "_ai_status",
            lambda: {"configured": True, "ok": True, "reason": None},
        )
        monkeypatch.setattr(
            strategy_selector.qwen_client,
            "plan_agent_turn",
            lambda _query, _context=None: AgentPlanResult(
                tool="stock_screen",
                tool_label="结构化股票筛选",
                reasoning="empty",
                conditions=[],
            ),
        )

        res = strategy_selector.run_agent_selection(db, "随便看看", limit=10)

        assert res.plan.tool == "ask_clarification"
        assert res.screen_result is None
        assert any("已阻止无条件全市场筛选" in w for w in res.warnings)
