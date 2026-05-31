from app.services import strategy_selector


def test_agent_uses_local_screen_when_ai_unavailable(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": True, "ok": False, "reason": "模型不可用: test-model"},
    )

    def fail_parse(_query):
        raise AssertionError("AI parser should not be called when health is unavailable")

    monkeypatch.setattr(strategy_selector.qwen_client, "parse_nl_query", fail_parse)

    res = strategy_selector.run_agent_selection(db, "半导体行业里的大市值龙头", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_configured is True
    assert res.plan.ai_used is False
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.screen_result.items[0].code == "688981.SH"
    assert "模型不可用" in res.warnings[0]
    assert res.tool_trace == ["调用 screener_engine.screen(conditions=2, limit=10)"]


def test_agent_reports_unconfigured_ai_but_still_runs_tool(db, seed_stocks, monkeypatch):
    monkeypatch.setattr(
        strategy_selector,
        "_ai_status",
        lambda: {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"},
    )

    res = strategy_selector.run_agent_selection(db, "低估值银行", limit=10)

    assert res.plan.tool == "stock_screen"
    assert res.plan.ai_configured is False
    assert res.plan.ai_used is False
    assert res.screen_result is not None
    assert res.screen_result.total == 1
    assert res.screen_result.items[0].code == "600036.SH"
    assert "AI 服务未配置" in res.warnings[0]


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
