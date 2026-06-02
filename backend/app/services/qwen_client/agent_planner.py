"""模型 Function Calling Agent 规划适配器。

向模型暴露五个工具，由模型自主选择并生成结构化参数；
后端校验通过后才使用，否则回退本地规则 Agent。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings
from app.schemas.screener import ALLOWED_FIELDS, FilterCondition
from .transport import openai_client

# ---------------------------------------------------------------------------
# 五个模型可见工具
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "stock_screen",
            "description": (
                "执行股票筛选。将自然语言选股需求转换为结构化条件，"
                "调用本地筛选引擎返回匹配的A股列表。"
                "仅在用户给出了具体筛选条件（行业、估值范围、财务指标等）时使用。"
                "模糊不清的需求不要用此工具。"
                "用户明确提出「全部股票/全市场/不设条件/不限条件」时，conditions可以为空数组。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "conditions": {
                        "type": "array",
                        "description": "筛选条件列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "enum": sorted(ALLOWED_FIELDS),
                                },
                                "op": {
                                    "type": "string",
                                    "enum": ["gt", "gte", "lt", "lte", "eq", "between", "in"],
                                },
                                "value": {
                                    "description": (
                                        "between → [低, 高] 数组；"
                                        "in → 字符串数组（仅 industry/market）；"
                                        "其他 → 单个数或字符串"
                                    ),
                                },
                            },
                            "required": ["field", "op", "value"],
                        },
                    },
                    "logic": {"type": "string", "enum": ["AND", "OR"], "default": "AND"},
                    "sort_by": {
                        "type": "string",
                        "enum": sorted(ALLOWED_FIELDS | {"score", "change_pct"}),
                        "description": "排序字段",
                    },
                    "sort_desc": {"type": "boolean", "default": True},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
                },
                "required": ["conditions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "strategy_design",
            "description": (
                "仅设计选股策略、列出量化条件，不执行实际股票筛选。"
                "当用户明确说「只列/只设计/不要筛/不筛选/不用筛/不执行/先别跑」时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "quantitative_conditions": {
                        "type": "array",
                        "description": "建议的量化条件（中文描述，如 ROE不低于15）",
                        "items": {"type": "string"},
                    },
                    "framework": {
                        "type": "string",
                        "description": "策略框架简述",
                    },
                    "notes": {
                        "type": "string",
                        "description": "执行时需要注意的事项",
                    },
                },
                "required": ["quantitative_conditions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "strategy_select",
            "description": (
                "执行内置选股策略。可用策略："
                "turtle_breakout（海龟突破：突破20日新高）、"
                "ma_volume（均线放量：5日线上穿20日线且放量）、"
                "rps_breakout（RPS强势突破：120日相对强度前10%）、"
                "high_tight_flag（高位窄幅整理：强势后的缩量旗形整理）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "string",
                        "enum": ["turtle_breakout", "ma_volume", "rps_breakout", "high_tight_flag"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 50,
                    },
                },
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_result",
            "description": (
                "解释上一轮筛选结果，不重新执行筛选。"
                "当用户追问为什么这些股票被选中、怎么看某只股票、分析结果时使用。"
                "仅在对话上下文中有上一轮结果时使用，否则应使用 ask_clarification。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "用户想重点了解的方向",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "当用户需求过于模糊、没有给出可执行的筛选条件时，请求补充信息。"
                "不执行任何筛选。适用于「帮我选点好股票」「推荐几个」「有什么可以买」等过于宽泛的请求。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "missing_info": {
                        "type": "array",
                        "description": "需要用户补充的信息类别",
                        "items": {
                            "type": "string",
                            "enum": ["行业", "风格偏好", "估值范围", "持有周期", "风险承受"],
                        },
                    },
                    "question": {
                        "type": "string",
                        "description": "向用户提出的具体澄清问题",
                    },
                },
                "required": ["missing_info"],
            },
        },
    },
]

ALLOWED_TOOLS: frozenset[str] = frozenset(t["function"]["name"] for t in TOOLS)

VALID_SORT_FIELDS: frozenset[str] = ALLOWED_FIELDS | {"score", "change_pct"}
STRING_FIELDS: frozenset[str] = frozenset({"industry", "market"})

VALID_STRATEGY_IDS: frozenset[str] = frozenset({
    "turtle_breakout", "ma_volume", "rps_breakout", "high_tight_flag",
})


# ---------------------------------------------------------------------------
# Pydantic 校验模型（模型输出不可信，必须校验）
# ---------------------------------------------------------------------------

class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ConditionArg(_StrictArgs):
    field: str
    op: str
    value: Any

    @field_validator("field")
    @classmethod
    def _valid_field(cls, v: str) -> str:
        if v not in ALLOWED_FIELDS:
            raise ValueError(f"非法字段: {v}")
        return v

    @field_validator("op")
    @classmethod
    def _valid_op(cls, v: str) -> str:
        if v not in ("gt", "gte", "lt", "lte", "eq", "between", "in"):
            raise ValueError(f"非法操作符: {v}")
        return v

    @model_validator(mode="after")
    def _valid_value(self) -> "_ConditionArg":
        if self.field in STRING_FIELDS:
            if self.op == "eq" and isinstance(self.value, str) and self.value:
                return self
            if self.op == "in" and isinstance(self.value, list) and self.value and all(
                isinstance(item, str) and item for item in self.value
            ):
                return self
            raise ValueError(f"{self.field} 仅支持非空字符串 eq 或非空字符串数组 in")

        if self.op == "between":
            if isinstance(self.value, list) and len(self.value) == 2 and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in self.value
            ):
                return self
            raise ValueError("between 需要两个数字")
        if self.op == "in":
            if isinstance(self.value, list) and self.value and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in self.value
            ):
                return self
            raise ValueError("数值字段的 in 需要非空数字数组")
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            return self
        raise ValueError(f"{self.field} 需要数字阈值")


class StockScreenArgs(_StrictArgs):
    conditions: list[_ConditionArg] = Field(default_factory=list, max_length=20)
    logic: str = "AND"
    sort_by: str | None = None
    sort_desc: bool = True
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("logic")
    @classmethod
    def _valid_logic(cls, v: str) -> str:
        if v not in ("AND", "OR"):
            raise ValueError(f"非法逻辑: {v}")
        return v

    @field_validator("sort_by")
    @classmethod
    def _valid_sort(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_SORT_FIELDS:
            raise ValueError(f"非法排序字段: {v}")
        return v


class StrategyDesignArgs(_StrictArgs):
    quantitative_conditions: list[str] = Field(default_factory=list, max_length=20)
    framework: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=500)


class StrategySelectArgs(_StrictArgs):
    strategy_id: str
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("strategy_id")
    @classmethod
    def _valid_strategy(cls, v: str) -> str:
        if v not in VALID_STRATEGY_IDS:
            raise ValueError(f"未知策略: {v}")
        return v


class ExplainResultArgs(_StrictArgs):
    focus: str = Field(default="", max_length=200)


class AskClarificationArgs(_StrictArgs):
    missing_info: list[str] = Field(default_factory=list, max_length=5)
    question: str = Field(default="", max_length=300)

    @field_validator("missing_info")
    @classmethod
    def _valid_missing_info(cls, value: list[str]) -> list[str]:
        allowed = {"行业", "风格偏好", "估值范围", "持有周期", "风险承受"}
        if any(item not in allowed for item in value):
            raise ValueError("missing_info 包含未知类别")
        return value


TOOL_ARGS_SCHEMA: dict[str, type[BaseModel]] = {
    "stock_screen": StockScreenArgs,
    "strategy_design": StrategyDesignArgs,
    "strategy_select": StrategySelectArgs,
    "explain_result": ExplainResultArgs,
    "ask_clarification": AskClarificationArgs,
}

TOOL_LABELS: dict[str, str] = {
    "stock_screen": "结构化股票筛选",
    "strategy_design": "策略设计",
    "strategy_select": "策略选股",
    "explain_result": "结果解释",
    "ask_clarification": "补充追问",
}


# ---------------------------------------------------------------------------
# 公共结果类型
# ---------------------------------------------------------------------------

class AgentPlanResult(BaseModel):
    """校验后的模型规划结果。调用方据此构造 StrategyAgentPlan。"""
    tool: str
    tool_label: str
    reasoning: str
    conditions: list[FilterCondition] = Field(default_factory=list)
    logic: str = "AND"
    sort_by: str | None = None
    sort_desc: bool = True
    limit: int = 50
    offset: int = 0
    strategy_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def plan_agent_turn(
    query: str,
    context: dict[str, Any] | None = None,
) -> AgentPlanResult | None:
    """尝试用模型 Function Calling 规划一次对话回合。

    成功返回校验后的 AgentPlanResult；任何失败返回 None（调用方回退本地规则）。
    """
    chat_client = _agent_chat_client()
    if chat_client is None:
        return None
    client, model, backend = chat_client

    messages = _build_messages(query, context)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            timeout=30.0,
        )
    except Exception as e:
        logger.info("Agent FC 不可用，回退本地规则: {}", str(e)[:120])
        return None

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    if not tool_calls:
        logger.info("模型未选择工具，回退本地规则")
        return None

    tc = tool_calls[0]
    tool_name = tc.function.name

    if tool_name not in ALLOWED_TOOLS:
        logger.info("模型选择了未知工具 '{}'，回退本地规则", tool_name)
        return None

    try:
        raw_args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        logger.info("模型工具参数非 JSON，回退本地规则: {}", str(e)[:80])
        return None

    schema = TOOL_ARGS_SCHEMA[tool_name]
    try:
        validated = schema(**raw_args)
    except Exception as e:
        logger.info("工具参数校验失败（{}），回退本地规则: {}", tool_name, str(e)[:120])
        return None

    result = _to_plan_result(tool_name, validated, query)
    logger.info(
        "Agent FC 成功: tool={} backend={}",
        tool_name,
        backend,
    )
    return result


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _agent_chat_client():
    """Return an OpenAI-compatible chat client for Agent tool calling."""
    backend = (settings.ai_backend or "openai").lower()
    if backend == "openai":
        if not settings.openai_api_key:
            return None
        try:
            return openai_client(), settings.openai_model, "openai"
        except RuntimeError as e:
            logger.info("Agent FC OpenAI 客户端不可用，回退本地规则: {}", str(e)[:120])
            return None

    if backend == "dashscope":
        if not settings.dashscope_api_key:
            return None
        try:
            return _dashscope_openai_client(), settings.qwen_model, "dashscope"
        except RuntimeError as e:
            logger.info("Agent FC DashScope 客户端不可用，回退本地规则: {}", str(e)[:120])
            return None

    logger.info("Agent FC 暂不支持当前 AI provider={}，回退本地规则", backend)
    return None


def _dashscope_openai_client():
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 未安装，请 pip install -r requirements.txt") from e
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

def _build_messages(query: str, context: dict[str, Any] | None) -> list[dict]:
    system = (
        "你是A股量化筛选助手。根据用户输入选择最合适的工具。\n"
        "规则：\n"
        "1. 有具体筛选条件（行业、估值、财务指标等）→ stock_screen\n"
        "2. 明确说「只列/设计/不执行/先别跑」 → strategy_design\n"
        "3. 提到海龟/突破/均线/放量/RPS/强势/窄幅整理 → strategy_select\n"
        "4. 追问为什么/怎么看/分析结果（有上下文时）→ explain_result\n"
        "5. 模糊无具体条件 → ask_clarification\n"
        "6. 「全部股票/全市场/不设条件」→ stock_screen with conditions=[]\n"
        "7. 结合对话上下文处理承接语：确认执行时沿用上一轮条件；"
        "调整排序时只修改 sort_by/sort_desc；换一批时沿用条件并增加 offset；"
        "追问命中原因时使用 explain_result，不要重新筛选。"
        "如果上下文不足，使用 ask_clarification。\n"
        "翻译：低估值=pe<15且pb<2；高分红=dividend_yield>3；"
        "成长=revenue_yoy>20且profit_yoy>20；白马=roe>15且market_cap>500；"
        "小盘=market_cap<100；中盘=market_cap between [100,500]；大盘=market_cap>500。"
        "industry用中文短词。"
    )

    messages: list[dict] = [{"role": "system", "content": system}]

    # 紧凑上下文注入：限制长度，避免把完整股票池和历史消息塞给模型。
    if context:
        context_summary: dict[str, Any] = {
            "session_id": context.get("session_id"),
            "上一轮问题": str(context.get("last_query") or "")[:180],
            "上一轮工具": (context.get("last_plan") or {}).get("tool")
            if isinstance(context.get("last_plan"), dict)
            else None,
            "上一轮回答": str(context.get("last_answer") or "")[:240],
            "上一轮条件": (context.get("last_conditions") or [])[:10],
            "上一轮工具调用": [
                {
                    "name": call.get("name"),
                    "label": call.get("label"),
                    "status": call.get("status"),
                    "message": str(call.get("message") or "")[:120],
                }
                for call in (context.get("last_tool_calls") or [])[-6:]
                if isinstance(call, dict)
            ],
            "最近对话": (context.get("recent_turns") or [])[-6:],
        }
        last_result = context.get("last_result") if isinstance(context, dict) else None
        if isinstance(last_result, dict):
            items = last_result.get("items") or []
            if isinstance(items, list):
                context_summary["上一轮前排股票"] = [
                    {"code": it.get("code"), "name": it.get("name")}
                    for it in items[:5]
                    if isinstance(it, dict)
                ]
                context_summary["上一轮命中数"] = last_result.get("total", 0)
            conds = (
                last_result.get("parsed_conditions")
                or context.get("last_conditions")
                or []
            )
            if conds:
                context_summary["上一轮条件"] = conds[:10]
        messages.append({
            "role": "system",
            "content": "对话上下文（仅供判断意图）：\n"
            + json.dumps(context_summary, ensure_ascii=False),
        })

    messages.append({"role": "user", "content": query})
    return messages


def _to_plan_result(
    tool_name: str,
    args: BaseModel,
    query: str,
) -> AgentPlanResult:
    label = TOOL_LABELS[tool_name]

    if tool_name == "stock_screen":
        args: StockScreenArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="AI 将自然语言目标转换为结构化筛选条件。",
            conditions=[
                FilterCondition(field=c.field, op=c.op, value=c.value)
                for c in args.conditions
            ],
            logic=args.logic,
            sort_by=args.sort_by,
            sort_desc=args.sort_desc,
            limit=args.limit,
            offset=args.offset,
        )

    if tool_name == "strategy_design":
        args: StrategyDesignArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="用户请求是设计策略/列条件，不执行筛选。",
            extra={
                "quantitative_conditions": args.quantitative_conditions,
                "framework": args.framework,
                "notes": args.notes,
            },
        )

    if tool_name == "strategy_select":
        args: StrategySelectArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning=f"用户目标匹配内置策略 {args.strategy_id}。",
            strategy_id=args.strategy_id,
            limit=args.limit,
        )

    if tool_name == "explain_result":
        args: ExplainResultArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="用户追问上一轮结果，基于上下文解释。",
            extra={"focus": args.focus},
        )

    # ask_clarification
    args: AskClarificationArgs
    return AgentPlanResult(
        tool=tool_name,
        tool_label=label,
        reasoning="用户需求模糊，请求补充信息。",
        extra={
            "missing_info": args.missing_info,
            "question": args.question,
        },
    )
