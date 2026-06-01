import json
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
