"""qwen_client 包：AI 大模型业务封装。

公开能力：
- parse_nl_query(query)           自然语言 → ScreenRequest（FC + 缓存 + JSON 模式兜底）
- plan_agent_turn(query, context) 模型 FC Agent 规划（六工具，校验后返回）
- analyze_stock(snapshot)         基于基本面数据生成投资分析（缓存）
- stream_analyze_stock(snapshot)  流式版本，yields 字符串 chunks
- stream_call(prompt)             裸流式调用（不预设 prompt 模板）
- probe_health()                  探测上游 AI 是否可用

底层 transport（OpenAI Responses / Chat / DashScope / 重试 / 错误清洗）见 .transport。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings
from app.schemas.screener import ScreenRequest

from .agent_planner import plan_agent_turn
from .transport import call as _call, openai_client, probe_health, stream_call

__all__ = [
    "parse_nl_query",
    "plan_agent_turn",
    "analyze_stock",
    "stream_analyze_stock",
    "stream_call",
    "probe_health",
]


PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------- JSON 容错抽取 ----------------------

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """容错地从模型输出里抠出 JSON。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"模型返回非 JSON: {text[:200]}")


# ---------------------- Function Calling tool schema ----------------------

_SCREEN_TOOL = {
    "type": "function",
    "function": {
        "name": "screen_stocks",
        "description": "Apply structured filters to A-share stocks and return matches.",
        "parameters": {
            "type": "object",
            "properties": {
                "conditions": {
                    "type": "array",
                    "description": "List of filter conditions to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": [
                                    "pe", "pb", "roe", "market_cap", "dividend_yield",
                                    "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio",
                                    "industry", "market", "close", "turnover",
                                ],
                                "description": "字段：pe(倍)、pb(倍)、roe(%)、market_cap(亿元)、dividend_yield(%)、revenue_yoy(%)、profit_yoy(%)、gross_margin(%)、debt_ratio(%)、close(元)、turnover(%)、industry(字符串)、market(主板/创业板/科创板/北交所)",
                            },
                            "op": {"type": "string", "enum": ["gt", "gte", "lt", "lte", "eq", "between", "in"]},
                            "value": {"description": "between → [低,高] 数组；in → 字符串数组（仅 industry/market）；其他 → 单个数或字符串"},
                        },
                        "required": ["field", "op", "value"],
                    },
                },
                "logic": {"type": "string", "enum": ["AND", "OR"], "default": "AND"},
                "sort_by": {"type": "string", "description": "排序字段，可为空"},
                "sort_desc": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            },
            "required": ["conditions"],
        },
    },
}


def _openai_call_tool(user_query: str) -> dict | None:
    """Function Calling 路径：让模型直接生成结构化参数。
    成功返回参数 dict；任何失败/不支持都返回 None，由调用方走 JSON 模式兜底。
    """
    if not settings.openai_api_key:
        return None
    try:
        client = openai_client()
        sys_msg = (
            "你是一个 A 股量化筛选助手。把用户的自然语言筛选需求转成 screen_stocks 工具调用。"
            "翻译规则：低估值=pe<15且pb<2；高分红=dividend_yield>3；成长股=revenue_yoy>20且profit_yoy>20；"
            "白马股=roe>15且market_cap>500；小盘股=market_cap<100，中盘=100~500，大盘>500。"
            "industry 用中文短词（银行/白酒/半导体/光伏/医药/新能源车）。"
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_query},
            ],
            tools=[_SCREEN_TOOL],
            tool_choice={"type": "function", "function": {"name": "screen_stocks"}},
            timeout=60.0,
        )
        msg = resp.choices[0].message
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            return None
        return json.loads(calls[0].function.arguments)
    except Exception as e:
        logger.warning("FC 路径不可用，回退 JSON: {}", str(e)[:120])
        return None


# ---------------------- 业务函数 ----------------------

def parse_nl_query(user_query: str) -> ScreenRequest:
    """自然语言 → ScreenRequest。优先级：缓存 → Function Calling → JSON-mode prompt。"""
    from app.services import cache as _cache

    key = _cache.make_key("nl", user_query.strip())
    cached = _cache.get_json(key)
    if cached is not None:
        try:
            return ScreenRequest(**cached)
        except Exception:
            pass  # 损坏的缓存：忽略并重新生成

    data = _openai_call_tool(user_query)
    if not data:
        prompt = _load_prompt("nl_to_filter.md").replace("{user_query}", user_query)
        text = _call(prompt, json_mode=True)
        data = _extract_json(text)

    req = ScreenRequest(**data)
    _cache.set_json(key, req.model_dump(), ttl=3600)
    return req


def analyze_stock(snapshot: dict) -> str:
    """生成投资分析文本，按 snapshot 哈希缓存（默认 1 小时 TTL）。"""
    from app.services import cache as _cache

    key = _cache.make_key("analyze", snapshot)
    cached = _cache.get_text(key)
    if cached:
        return cached

    template = _load_prompt("stock_analysis.md")
    for k, v in snapshot.items():
        template = template.replace("{" + k + "}", "" if v is None else str(v))
    text = _call(template, json_mode=False).strip()
    if text:
        _cache.set_text(key, text, ttl=3600)
    return text


def stream_analyze_stock(snapshot: dict):
    """流式生成投资分析。yields 每个 token chunk（字符串）。"""
    template = _load_prompt("stock_analysis.md")
    for k, v in snapshot.items():
        template = template.replace("{" + k + "}", "" if v is None else str(v))
    yield from stream_call(template)
