"""qwen_client 包：AI 大模型业务封装。

公开能力：
- parse_nl_query(query)         自然语言 → ScreenRequest（FC + 缓存 + JSON 模式兜底）
- analyze_stock(snapshot)       基于基本面数据生成投资分析（缓存）
- score_stock(snapshot)         千问 JSON 评分（长 TTL 缓存，省 API）
- formula_score(snapshot)       本地规则评分（不调 API）
- stream_analyze_stock(snapshot) 流式版本，yields 字符串 chunks
- stream_call(prompt)           裸流式调用（不预设 prompt 模板）
- probe_health()                探测上游 AI 是否可用

底层 transport（OpenAI Responses / Chat / DashScope / 重试 / 错误清洗）见 .transport。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings
from app.schemas.screener import ScreenRequest

from .transport import call as _call, openai_client, probe_health, stream_call

__all__ = [
    "parse_nl_query",
    "analyze_stock",
    "score_stock",
    "formula_score",
    "stream_analyze_stock",
    "stream_call",
    "probe_health",
]

_VERDICTS = ("强烈关注", "可关注", "中性", "谨慎")
_MEM_SCORE_CACHE: dict[str, tuple[float, dict]] = {}
_MEM_SCORE_MAX = 256


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


# ---------------------- 个股评分（千问 + 缓存） ----------------------

def _ai_configured() -> bool:
    backend = (settings.ai_backend or "openai").lower()
    if backend == "dashscope":
        return bool(settings.dashscope_api_key)
    return bool(settings.openai_api_key)


def _clamp_score(v: Any, default: int = 50) -> int:
    try:
        if v is None or v == "":
            return default
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _verdict_from_total(total: int) -> str:
    if total >= 80:
        return "强烈关注"
    if total >= 60:
        return "可关注"
    if total >= 40:
        return "中性"
    return "谨慎"


def _normalize_verdict(raw: Any, total: int) -> str:
    if isinstance(raw, str):
        s = raw.strip()
        for v in _VERDICTS:
            if v in s:
                return v
    return _verdict_from_total(total)


def formula_score(snapshot: dict) -> dict:
    """本地规则评分（与前端 Detail 原公式一致），不消耗 API。"""
    pe = snapshot.get("pe")
    roe = snapshot.get("roe")
    div = snapshot.get("dividend_yield")
    pe_score = (
        _clamp_score(110 - float(pe) * 4, 60)
        if pe is not None and float(pe) > 0
        else 60
    )
    roe_score = _clamp_score(40 + float(roe) * 4, 60) if roe is not None else 60
    growth = ((float(snapshot.get("revenue_yoy") or 0)) + (float(snapshot.get("profit_yoy") or 0))) / 2
    growth_score = _clamp_score(60 + growth * 1.5, 60)
    div_score = _clamp_score(50 + float(div) * 8, 50) if div is not None else 50

    total = 60
    if pe is not None and float(pe) > 0:
        total += max(0, min(20, 25 - float(pe) * 0.5))
    if div is not None:
        total += min(15, float(div) * 2)
    if roe is not None:
        total += min(15, float(roe))
    total = _clamp_score(total, 60)

    return {
        "code": snapshot.get("code", ""),
        "source": "formula",
        "cached": False,
        "total": total,
        "valuation": pe_score,
        "profit": roe_score,
        "growth": growth_score,
        "dividend": div_score,
        "verdict": _verdict_from_total(total),
        "reason": None,
    }


def _mem_cache_get(key: str) -> dict | None:
    hit = _MEM_SCORE_CACHE.get(key)
    if not hit:
        return None
    expires, payload = hit
    if time.time() > expires:
        _MEM_SCORE_CACHE.pop(key, None)
        return None
    return payload


def _mem_cache_set(key: str, payload: dict, ttl: int) -> None:
    if len(_MEM_SCORE_CACHE) >= _MEM_SCORE_MAX:
        oldest = min(_MEM_SCORE_CACHE.items(), key=lambda x: x[1][0])[0]
        _MEM_SCORE_CACHE.pop(oldest, None)
    _MEM_SCORE_CACHE[key] = (time.time() + ttl, payload)


def _parse_score_json(data: dict, snapshot: dict) -> dict:
    total = _clamp_score(data.get("total"), 60)
    return {
        "code": snapshot.get("code", ""),
        "source": "qwen",
        "cached": False,
        "total": total,
        "valuation": _clamp_score(data.get("valuation"), total),
        "profit": _clamp_score(data.get("profit"), total),
        "growth": _clamp_score(data.get("growth"), total),
        "dividend": _clamp_score(data.get("dividend"), total),
        "verdict": _normalize_verdict(data.get("verdict"), total),
        "reason": (str(data.get("reason") or "")[:80] or None),
    }


def score_stock(snapshot: dict, *, force_refresh: bool = False) -> dict:
    """千问 JSON 评分。Redis / 进程内缓存，默认 7 天 TTL；基本面快照变化会换 key。"""
    if not _ai_configured():
        raise RuntimeError("未配置 AI Key（DASHSCOPE_API_KEY 或 OPENAI_API_KEY）")

    from app.services import cache as _cache

    ttl = max(3600, int(settings.qwen_score_cache_ttl or 604800))
    key = _cache.make_key("score", snapshot)

    if not force_refresh:
        cached = _cache.get_json(key)
        if cached is not None:
            try:
                out = dict(cached)
                out["cached"] = True
                return out
            except Exception:
                pass
        mem = _mem_cache_get(key)
        if mem is not None:
            out = dict(mem)
            out["cached"] = True
            return out

    template = _load_prompt("stock_score.md")
    for k, v in snapshot.items():
        template = template.replace("{" + k + "}", "" if v is None else str(v))

    text = _call(template, json_mode=True)
    data = _extract_json(text)
    out = _parse_score_json(data, snapshot)

    _cache.set_json(key, out, ttl=ttl)
    _mem_cache_set(key, out, ttl)
    logger.info("[QWEN-SCORE] {} total={} (api call)", out.get("code"), out.get("total"))
    return out
