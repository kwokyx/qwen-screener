import json
import time
from types import SimpleNamespace

import pytest

from app.services.qwen_client import agent_planner


def _fake_client(tool_name: str, arguments, captured: dict | None = None):
    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        raw_arguments = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
        function = SimpleNamespace(name=tool_name, arguments=raw_arguments)
        message = SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )


def _configure(monkeypatch, tool_name: str, arguments, captured: dict | None = None):
    monkeypatch.setattr(agent_planner.settings, "ai_backend", "openai")
    monkeypatch.setattr(agent_planner.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        agent_planner,
        "openai_client",
        lambda: _fake_client(tool_name, arguments, captured),
    )


def test_plan_agent_turn_accepts_valid_screen_and_compact_context(monkeypatch):
    captured = {}
    _configure(
        monkeypatch,
        "stock_screen",
        {
            "conditions": [
                {"field": "industry", "op": "in", "value": ["银行"]},
                {"field": "pe", "op": "lt", "value": 15},
            ],
            "sort_by": "dividend_yield",
            "limit": 20,
        },
        captured,
    )

    result = agent_planner.plan_agent_turn(
        "低估值高分红的银行股",
        context={
            "session_id": "session-1",
            "last_query": "先找低估值股票",
            "last_answer": "上一轮回答",
            "last_conditions": [{"field": "pe", "op": "lt", "value": 20}],
            "last_tool_calls": [
                {
                    "name": "stock_screen",
                    "label": "股票筛选",
                    "status": "done",
                    "message": "股票筛选完成",
                    "params": {"conditions": 1, "limit": 50},
                }
            ],
            "recent_turns": [{"query": "先找低估值股票", "tool": "stock_screen"}],
        },
    )

    assert result is not None
    assert result.tool == "stock_screen"
    assert result.limit == 20
    assert [(item.field, item.op, item.value) for item in result.conditions] == [
        ("industry", "in", ["银行"]),
        ("pe", "lt", 15),
    ]
    context_message = captured["messages"][1]["content"]
    assert "session-1" in context_message
    assert "最近对话" in context_message
    assert "上一轮工具调用" in context_message
    assert "股票筛选完成" in context_message
    assert "limit" not in context_message
    assert captured["timeout"] == agent_planner._AGENT_PLAN_TIMEOUT_SECONDS


def test_plan_agent_turn_accepts_known_market_value(monkeypatch):
    _configure(
        monkeypatch,
        "stock_screen",
        {
            "conditions": [
                {"field": "market", "op": "eq", "value": "主板"},
                {"field": "roe", "op": "gt", "value": 15},
            ],
        },
    )

    result = agent_planner.plan_agent_turn("ROE 大于 15 的主板股票")

    assert result is not None
    assert [(item.field, item.op, item.value) for item in result.conditions] == [
        ("market", "eq", "主板"),
        ("roe", "gt", 15),
    ]


def test_plan_agent_turn_rejects_a_share_market_value(monkeypatch):
    _configure(
        monkeypatch,
        "stock_screen",
        {
            "conditions": [
                {"field": "industry", "op": "eq", "value": "银行"},
                {"field": "market", "op": "eq", "value": "A股"},
            ],
        },
    )

    result = agent_planner.plan_agent_turn("低估值高分红的银行股")

    assert result is None
    assert agent_planner.last_plan_failure_reason() == "模型工具参数校验失败"


def test_plan_agent_turn_clamps_explicit_positive_profit_yoy(monkeypatch):
    _configure(
        monkeypatch,
        "stock_screen",
        {
            "conditions": [
                {"field": "roe", "op": "gt", "value": 15},
                {"field": "revenue_yoy", "op": "gt", "value": 20},
                {"field": "profit_yoy", "op": "gt", "value": 20},
            ],
        },
    )

    result = agent_planner.plan_agent_turn("ROE 大于 15 且最新季度净利润同比正增长的成长股")

    assert result is not None
    assert [(item.field, item.op, item.value) for item in result.conditions] == [
        ("roe", "gt", 15),
        ("profit_yoy", "gt", 0),
    ]


def test_plan_agent_turn_clamps_explicit_positive_revenue_and_profit_yoy(monkeypatch):
    _configure(
        monkeypatch,
        "stock_screen",
        {
            "conditions": [
                {"field": "revenue_yoy", "op": "gt", "value": 20},
                {"field": "profit_yoy", "op": "gt", "value": 20},
            ],
        },
    )

    result = agent_planner.plan_agent_turn("营收同比为正且净利润同比为正")

    assert result is not None
    assert [(item.field, item.op, item.value) for item in result.conditions] == [
        ("revenue_yoy", "gt", 0),
        ("profit_yoy", "gt", 0),
    ]


def test_plan_agent_turn_accepts_sort_results_tool(monkeypatch):
    _configure(monkeypatch, "sort_results", {"sort_by": "dividend_yield", "sort_desc": True})

    result = agent_planner.plan_agent_turn("按股息率排序", context={"last_result": {"total": 3}})

    assert result is not None
    assert result.tool == "sort_results"
    assert result.sort_by == "dividend_yield"
    assert result.sort_desc is True
    assert result.conditions == []


def test_plan_agent_turn_accepts_paginate_results_tool(monkeypatch):
    _configure(monkeypatch, "paginate_results", {"limit": 20})

    result = agent_planner.plan_agent_turn("换一批", context={"last_result": {"total": 3}})

    assert result is not None
    assert result.tool == "paginate_results"
    assert result.limit == 20
    assert result.conditions == []


def test_plan_agent_turn_hard_times_out_slow_model(monkeypatch):
    def create(**_kwargs):
        time.sleep(0.08)
        return _fake_client("ask_clarification", {"question": "迟到的响应"}).chat.completions.create()

    monkeypatch.setattr(agent_planner.settings, "ai_backend", "openai")
    monkeypatch.setattr(agent_planner.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(agent_planner, "_AGENT_PLAN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        agent_planner,
        "openai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    assert agent_planner.plan_agent_turn("你好") is None


def test_plan_react_step_uses_configured_timeout(monkeypatch):
    captured = {}
    _configure(
        monkeypatch,
        "stock_screen",
        {"conditions": [{"field": "industry", "op": "in", "value": ["银行"]}]},
        captured,
    )

    result = agent_planner.plan_react_step("低估值银行股")

    assert result is not None
    assert result.kind == "action"
    assert captured["timeout"] == agent_planner._AGENT_REACT_STEP_TIMEOUT_SECONDS


def test_react_prompt_keeps_known_strategy_routes():
    messages = agent_planner._build_react_messages("找最近强势突破的股票", {}, [], 1)
    system_prompt = messages[0]["content"]
    tools_json = json.dumps(agent_planner.TOOLS, ensure_ascii=False)

    assert "内置策略请求必须用 strategy_select" in system_prompt
    assert "最近强势/强势突破/突破股票" in system_prompt
    assert "turtle_breakout" in system_prompt
    assert "rps_breakout" in system_prompt
    assert "均线放量/放量上攻" in system_prompt
    assert "最近强势/强势突破/突破股票" in tools_json


def test_plan_agent_turn_supports_dashscope_compatible_function_call(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_planner.settings, "ai_backend", "dashscope")
    monkeypatch.setattr(agent_planner.settings, "dashscope_api_key", "dash-key")
    monkeypatch.setattr(agent_planner.settings, "qwen_model", "qwen-test")
    monkeypatch.setattr(
        agent_planner,
        "_dashscope_openai_client",
        lambda: _fake_client(
            "ask_clarification",
            {"missing_info": ["行业"], "question": "请补充行业或风格偏好。"},
            captured,
        ),
    )

    result = agent_planner.plan_agent_turn("帮我选点好股票")

    assert result is not None
    assert result.tool == "ask_clarification"
    assert result.extra["question"] == "请补充行业或风格偏好。"
    assert captured["model"] == "qwen-test"
    assert captured["tools"] == agent_planner.TOOLS


def test_plan_agent_turn_accepts_stock_detail(monkeypatch):
    _configure(
        monkeypatch,
        "stock_detail",
        {"code": "600036.SH", "name": "招商银行"},
    )

    result = agent_planner.plan_agent_turn("打开招商银行详情")

    assert result is not None
    assert result.tool == "stock_detail"
    assert result.extra == {"code": "600036.SH", "name": "招商银行"}


def test_plan_agent_turn_accepts_clarification_question_only(monkeypatch):
    _configure(
        monkeypatch,
        "ask_clarification",
        {"question": "请补充行业、风格或风险偏好。"},
    )

    result = agent_planner.plan_agent_turn("你好")

    assert result is not None
    assert result.tool == "ask_clarification"
    assert result.extra == {
        "missing_info": [],
        "question": "请补充行业、风格或风险偏好。",
    }


def test_plan_agent_turn_normalizes_clarification_missing_info(monkeypatch):
    _configure(
        monkeypatch,
        "ask_clarification",
        {
            "missing_info": ["股票类型", "风险偏好", "未知类别", "行业板块"],
            "question": "你更偏向什么风格和行业？",
        },
    )

    result = agent_planner.plan_agent_turn("帮我选点好股票")

    assert result is not None
    assert result.tool == "ask_clarification"
    assert result.extra["missing_info"] == ["风格偏好", "风险承受", "行业"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"conditions": [{"field": "not_exists", "op": "lt", "value": 15}]},
        {"conditions": [{"field": "industry", "op": "gt", "value": 10}]},
        {"conditions": [{"field": "pe", "op": "between", "value": [1]}]},
        {"conditions": [{"field": "pe", "op": "lt", "value": "15"}]},
        {"conditions": [], "sort_by": "unknown_sort"},
        {"conditions": [], "offset": 10_001},
        {"conditions": [], "unexpected": "value"},
    ],
)
def test_plan_agent_turn_rejects_invalid_screen_arguments(monkeypatch, arguments):
    _configure(monkeypatch, "stock_screen", arguments)

    assert agent_planner.plan_agent_turn("测试") is None


def test_plan_agent_turn_rejects_unknown_tool(monkeypatch):
    _configure(monkeypatch, "dangerous_tool", {})

    assert agent_planner.plan_agent_turn("测试") is None


def test_plan_agent_turn_rejects_malformed_json(monkeypatch):
    _configure(monkeypatch, "stock_screen", "{not-json")

    assert agent_planner.plan_agent_turn("测试") is None
