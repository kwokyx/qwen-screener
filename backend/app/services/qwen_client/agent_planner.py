"""模型 Function Calling / ReAct Agent 规划适配器。

向模型暴露一组白名单工具，由模型自主选择并生成结构化参数；
后端校验通过后才使用，否则由调用方安全停止或走兼容处理。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import ContextVar
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings
from app.schemas.screener import ALLOWED_FIELDS, FilterCondition
from .transport import openai_client

_AGENT_PLAN_TIMEOUT_SECONDS = float(settings.agent_plan_timeout_seconds)
_AGENT_REACT_STEP_TIMEOUT_SECONDS = float(settings.agent_react_step_timeout_seconds)
_LAST_PLAN_FAILURE_REASON: ContextVar[str | None] = ContextVar(
    "last_agent_plan_failure_reason",
    default=None,
)


def reset_plan_failure_reason() -> None:
    _LAST_PLAN_FAILURE_REASON.set(None)


def last_plan_failure_reason() -> str | None:
    return _LAST_PLAN_FAILURE_REASON.get()


def _fail_plan(reason: str) -> None:
    _LAST_PLAN_FAILURE_REASON.set(reason)

# ---------------------------------------------------------------------------
# 模型可见工具
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "stock_screen",
            "description": (
                "执行A股筛选；只用于明确条件。模糊需求或不支持字段用 ask_clarification。"
                "只有用户明确说全部股票/全市场/不设条件时 conditions 才可为空。"
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
                                        "between=[低,高]；in=字符串数组（仅 industry/market）；其他=单值"
                                    ),
                                },
                            },
                            "required": ["field", "op", "value"],
                        },
                    },
                    "logic": {"type": "string", "enum": ["AND", "OR"], "default": "AND"},
                    "sort_by": {
                        "type": "string",
                        "enum": sorted(ALLOWED_FIELDS | {"change_pct"}),
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
                "只设计/列出量化条件，不执行筛选；用户说不筛选、不执行、先别跑时使用。"
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
                "执行内置策略：turtle_breakout、ma_volume、rps_breakout、"
                "high_tight_flag、limit_up_shakeout、uptrend_limit_down。"
                "最近强势/强势突破/突破股票用 turtle_breakout 或 rps_breakout；"
                "均线放量/放量上攻用 ma_volume；涨停后承接/涨停回踩用 limit_up_shakeout；"
                "高位旗形/高紧旗形用 high_tight_flag。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "string",
                        "enum": [
                            "turtle_breakout",
                            "ma_volume",
                            "rps_breakout",
                            "high_tight_flag",
                            "limit_up_shakeout",
                            "uptrend_limit_down",
                        ],
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
                "解释上一轮结果，不筛选；无上一轮结果时用 ask_clarification。"
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
            "name": "sort_results",
            "description": (
                "调整上一轮结果排序，不生成新条件；无上一轮结果时用 ask_clarification。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": sorted(ALLOWED_FIELDS | {"change_pct"}),
                        "description": "排序字段",
                    },
                    "sort_desc": {"type": "boolean", "default": True},
                },
                "required": ["sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paginate_results",
            "description": (
                "查看上一轮结果下一批，不生成新条件；无上一轮结果时用 ask_clarification。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_detail",
            "description": (
                "定位某只股票的详情页，不重新执行筛选。"
                "当用户明确要求查看/打开某只股票详情，或说查看第一只/第二只详情时使用。"
                "如果无法从用户输入或上下文确定股票，应使用 ask_clarification。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "股票代码，如 600036.SH；无法确定时留空",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称，如 招商银行；无法确定时留空",
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
                        "description": (
                            "需要用户补充的信息类别。建议值：行业、风格偏好、估值范围、持有周期、风险承受。"
                            "不确定时可以省略或传空数组。"
                        ),
                        "items": {
                            "type": "string",
                        },
                    },
                    "question": {
                        "type": "string",
                        "description": "向用户提出的具体澄清问题",
                    },
                },
            },
        },
    },
]

ALLOWED_TOOLS: frozenset[str] = frozenset(t["function"]["name"] for t in TOOLS)

VALID_SORT_FIELDS: frozenset[str] = ALLOWED_FIELDS | {"change_pct"}
STRING_FIELDS: frozenset[str] = frozenset({"industry", "market"})
VALID_MARKET_VALUES: frozenset[str] = frozenset({"主板", "创业板", "科创板", "北交所"})

VALID_STRATEGY_IDS: frozenset[str] = frozenset({
    "turtle_breakout",
    "ma_volume",
    "rps_breakout",
    "high_tight_flag",
    "limit_up_shakeout",
    "uptrend_limit_down",
})
PROFIT_YOY_TERMS: tuple[str, ...] = ("净利润同比", "净利同比", "利润同比")
REVENUE_YOY_TERMS: tuple[str, ...] = ("营收同比", "收入同比", "营业收入同比", "销售同比")
POSITIVE_GROWTH_TERMS: tuple[str, ...] = ("正增长", "为正", "大于0", "大于 0", ">0", "＞0")
VALID_MISSING_INFO: frozenset[str] = frozenset({
    "行业", "风格偏好", "估值范围", "持有周期", "风险承受",
})
MISSING_INFO_ALIASES: dict[str, str] = {
    "行业板块": "行业",
    "板块": "行业",
    "赛道": "行业",
    "主题": "行业",
    "股票类型": "风格偏好",
    "类型": "风格偏好",
    "风格": "风格偏好",
    "投资风格": "风格偏好",
    "指标偏好": "风格偏好",
    "估值": "估值范围",
    "估值水平": "估值范围",
    "价格范围": "估值范围",
    "周期": "持有周期",
    "投资周期": "持有周期",
    "时间周期": "持有周期",
    "风险": "风险承受",
    "风险偏好": "风险承受",
    "风险承受能力": "风险承受",
}


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
            if self.field == "market":
                values = self.value if isinstance(self.value, list) else [self.value]
                if not all(isinstance(item, str) and item in VALID_MARKET_VALUES for item in values):
                    raise ValueError("market 仅支持：主板、创业板、科创板、北交所；A股/全A是默认股票池，不应作为 market 条件")
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


class SortResultsArgs(_StrictArgs):
    sort_by: str
    sort_desc: bool = True

    @field_validator("sort_by")
    @classmethod
    def _valid_sort(cls, v: str) -> str:
        if v not in VALID_SORT_FIELDS:
            raise ValueError(f"非法排序字段: {v}")
        return v


class PaginateResultsArgs(_StrictArgs):
    limit: int = Field(default=50, ge=1, le=200)


class StockDetailArgs(_StrictArgs):
    code: str = Field(default="", max_length=16)
    name: str = Field(default="", max_length=40)


class AskClarificationArgs(_StrictArgs):
    missing_info: list[str] = Field(default_factory=list)
    question: str = Field(default="", max_length=300)

    @field_validator("missing_info", mode="before")
    @classmethod
    def _coerce_missing_info(cls, value: Any) -> list[Any]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return value
        return []

    @field_validator("missing_info")
    @classmethod
    def _normalize_missing_info(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            text = MISSING_INFO_ALIASES.get(text, text)
            if text in VALID_MISSING_INFO and text not in normalized:
                normalized.append(text)
        return normalized[:5]


TOOL_ARGS_SCHEMA: dict[str, type[BaseModel]] = {
    "stock_screen": StockScreenArgs,
    "strategy_design": StrategyDesignArgs,
    "strategy_select": StrategySelectArgs,
    "explain_result": ExplainResultArgs,
    "sort_results": SortResultsArgs,
    "paginate_results": PaginateResultsArgs,
    "stock_detail": StockDetailArgs,
    "ask_clarification": AskClarificationArgs,
}

TOOL_LABELS: dict[str, str] = {
    "stock_screen": "结构化股票筛选",
    "strategy_design": "策略设计",
    "strategy_select": "策略选股",
    "explain_result": "结果解释",
    "sort_results": "结果排序",
    "paginate_results": "结果分页",
    "stock_detail": "个股详情",
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


class AgentReactDecision(BaseModel):
    """一次 bounded ReAct step 的模型决策。

    kind=action 时由后端执行 plan 指向的工具；
    kind=final 时只使用 final_answer 对用户作答，不再调用工具。
    """
    kind: str
    public_reason: str = ""
    plan: AgentPlanResult | None = None
    final_answer: str = ""


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
    reset_plan_failure_reason()
    chat_client = _agent_chat_client()
    if chat_client is None:
        _fail_plan("模型工具规划客户端不可用")
        return None
    client, model, backend = chat_client

    messages = _build_messages(query, context)
    try:
        resp = _create_chat_completion_with_timeout(client, model, messages)
    except FutureTimeoutError:
        logger.info("Agent FC 超过 {} 秒，回退本地规则", _AGENT_PLAN_TIMEOUT_SECONDS)
        _fail_plan(f"模型规划超过 {_AGENT_PLAN_TIMEOUT_SECONDS:g} 秒")
        return None
    except Exception as e:
        logger.info("Agent FC 不可用，回退本地规则: {}", str(e)[:120])
        _fail_plan("模型规划请求失败")
        return None

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    if not tool_calls:
        logger.info("模型未选择工具，回退本地规则")
        _fail_plan("模型未选择工具")
        return None

    result = _plan_result_from_tool_call(tool_calls[0], query)
    if result is None:
        return None
    logger.info(
        "Agent FC 成功: tool={} backend={}",
        result.tool,
        backend,
    )
    return result


def plan_react_step(
    query: str,
    context: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    *,
    step_index: int = 1,
) -> AgentReactDecision | None:
    """让模型执行一次 bounded ReAct 决策。

    模型可以选择一个工具 action，也可以在已有 observation 后给出 final。
    任何非法工具、非法 JSON/schema、超时或请求失败都返回 None，由 orchestrator
    安全停止或返回普通回复；用户入口不会自动执行本地筛选兜底。
    """
    reset_plan_failure_reason()
    chat_client = _agent_chat_client()
    if chat_client is None:
        _fail_plan("模型工具规划客户端不可用")
        return None
    client, model, backend = chat_client

    observations = observations or []
    messages = _build_react_messages(query, context or {}, observations, step_index)
    last_error: str | None = None
    for attempt in range(2):
        try:
            resp = _create_react_completion_with_timeout(client, model, messages)
        except FutureTimeoutError:
            logger.info("Agent ReAct step 超过 {} 秒", _AGENT_REACT_STEP_TIMEOUT_SECONDS)
            _fail_plan(f"模型 ReAct 步骤超过 {_AGENT_REACT_STEP_TIMEOUT_SECONDS:g} 秒")
            return None
        except Exception as e:
            logger.info("Agent ReAct step 不可用: {}", str(e)[:120])
            _fail_plan("模型 ReAct 请求失败")
            return None

        decision = _to_react_decision(resp, query)
        if decision is not None:
            logger.info(
                "Agent ReAct step 成功: kind={} tool={} backend={} step={}",
                decision.kind,
                decision.plan.tool if decision.plan else "",
                backend,
                step_index,
            )
            return decision

        last_error = last_plan_failure_reason() or "模型 ReAct 输出不合法"
        if attempt == 0:
            messages.append({
                "role": "system",
                "content": (
                    "上一条输出不符合工具 schema 或缺少可执行内容。"
                    "请只选择一个已提供工具，或直接给出面向用户的最终回答；"
                    "不要编造字段，不要输出私有推理。"
                ),
            })

    _fail_plan(last_error or "模型 ReAct 输出不合法")
    return None


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
            return _single_try_client(openai_client()), settings.openai_model, "openai"
        except RuntimeError as e:
            logger.info("Agent FC OpenAI 客户端不可用，回退本地规则: {}", str(e)[:120])
            return None

    if backend == "dashscope":
        if not settings.dashscope_api_key:
            return None
        try:
            return _single_try_client(_dashscope_openai_client()), settings.qwen_model, "dashscope"
        except RuntimeError as e:
            logger.info("Agent FC DashScope 客户端不可用，回退本地规则: {}", str(e)[:120])
            return None

    logger.info("Agent FC 暂不支持当前 AI provider={}，回退本地规则", backend)
    return None


def _single_try_client(client):
    """Disable SDK retries for planning; local rules are the retry/fallback path."""
    with_options = getattr(client, "with_options", None)
    if callable(with_options):
        return with_options(max_retries=0)
    return client


def _create_chat_completion_with_timeout(client, model: str, messages: list[dict]):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-plan")
    future = executor.submit(
        client.chat.completions.create,
        model=model,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        timeout=_AGENT_PLAN_TIMEOUT_SECONDS,
    )
    try:
        result = future.result(timeout=_AGENT_PLAN_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=False)
    return result


def _create_react_completion_with_timeout(client, model: str, messages: list[dict]):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-react")
    future = executor.submit(
        client.chat.completions.create,
        model=model,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        timeout=_AGENT_REACT_STEP_TIMEOUT_SECONDS,
    )
    try:
        result = future.result(timeout=_AGENT_REACT_STEP_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=False)
    return result


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
        "你是A股量化筛选工具路由器。只选择一个工具并给 JSON 参数。\n"
        "路由：具体筛选→stock_screen；只设计/不执行→strategy_design；内置突破/均线/RPS/涨停承接/急跌修复→strategy_select；"
        "解释上一轮→explain_result；排序上一轮→sort_results；换一批/下一页→paginate_results；个股详情→stock_detail；模糊或上下文不足→ask_clarification。\n"
        "全部股票/全市场/不设条件才允许 stock_screen conditions=[]。"
        "ask_clarification.missing_info 仅可用：行业、风格偏好、估值范围、持有周期、风险承受。\n"
        "支持字段仅限 pe、pb、roe、market_cap、dividend_yield、revenue_yoy、profit_yoy、gross_margin、debt_ratio、industry、market、close、turnover、ma5、ma20、volume_ratio_20、breakout_20、ma5_above_ma20、pct_change_20。"
        "market 仅用于主板/创业板/科创板/北交所；A股/全A是默认股票池，不要生成 market=A股。\n"
        "不支持三年CAGR/复合增速、扣非净利润、经营现金流、EPS/每股收益、PS/市销率、机构/基金/北向资金持仓、研报评级、目标价；"
        "遇到不支持字段必须 ask_clarification，不要改写成别的指标继续筛选。\n"
        "翻译：低估值=pe<15且pb<2；高分红=dividend_yield>3；"
        "成长=仅在用户未给出明确同比阈值时用 revenue_yoy>20 且 profit_yoy>20；净利润同比正增长=profit_yoy>0，不能额外添加 revenue_yoy；白马=roe>15且market_cap>500；"
        "小盘=market_cap<100；中盘=market_cap between [100,500]；大盘=market_cap>500。"
        "20日新高/突破=breakout_20 eq 1；放量=volume_ratio_20>1.5；均线多头/MA5高于MA20=ma5_above_ma20 eq 1；近20日涨幅=pct_change_20。"
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


def _compact_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
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
    return context_summary


def _build_react_messages(
    query: str,
    context: dict[str, Any],
    observations: list[dict[str, Any]],
    step_index: int,
) -> list[dict]:
    system = (
        "你是 bounded ReAct 工具路由器。每步只做一个 action 工具调用，或基于 observation 给中文 final。"
        "不要私有思考链。\n"
        "普通寒暄、能力说明、使用方式询问或非选股开放对话，直接给 final 普通回答，不要调用 ask_clarification。"
        "只有用户想筛股票但缺少必要条件时，才使用 ask_clarification。\n"
        "支持字段：pe、pb、roe、market_cap、dividend_yield、revenue_yoy、profit_yoy、gross_margin、debt_ratio、industry、market、close、turnover、ma5、ma20、volume_ratio_20、breakout_20、ma5_above_ma20、pct_change_20。\n"
        "market 仅用于主板/创业板/科创板/北交所；A股/全A是默认股票池，不要生成 market=A股。\n"
        "不支持：三年净利润CAGR/复合增速、扣非净利润、经营现金流、EPS/每股收益、PS/市销率、机构/基金/北向资金持仓、研报评级、目标价；必须 ask_clarification 或 final 说明，不能近似改写后筛选。\n"
        "stock_detail 只定位详情。explain_result/sort_results/paginate_results 必须有上一轮结果，否则 ask_clarification。"
        "strategy_design 默认不执行；确认执行只有上一轮有条件才可筛选。"
        "内置策略请求必须用 strategy_select，不要追问行业/估值：最近强势/强势突破/突破股票→turtle_breakout或rps_breakout；均线放量/放量上攻→ma_volume；涨停后承接/涨停回踩→limit_up_shakeout；高位旗形/高紧旗形→high_tight_flag。\n"
        "已有 observation 时优先 final，禁止重复相同工具参数。\n"
        "翻译：低估值=pe<15且pb<2；高分红=dividend_yield>3；成长=仅在用户未给出明确同比阈值时用 revenue_yoy>20 且 profit_yoy>20；净利润同比正增长=profit_yoy>0，不能额外添加 revenue_yoy；白马=roe>15且market_cap>500；小盘=market_cap<100；中盘=market_cap between [100,500]；大盘=market_cap>500；20日新高/突破=breakout_20 eq 1；放量=volume_ratio_20>1.5；均线多头/MA5高于MA20=ma5_above_ma20 eq 1；近20日涨幅=pct_change_20。"
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    compact_context = _compact_context(context)
    if compact_context:
        messages.append({
            "role": "system",
            "content": "对话上下文（仅供判断意图）：\n"
            + json.dumps(compact_context, ensure_ascii=False),
        })
    if observations:
        safe_observations = observations[-4:]
        messages.append({
            "role": "system",
            "content": "已经执行过的工具 observation（请基于这些决定下一步或最终回答）：\n"
            + json.dumps(safe_observations, ensure_ascii=False, default=str),
        })
    messages.append({
        "role": "user",
        "content": f"用户请求：{query}\n当前 ReAct 步骤：{step_index}",
    })
    return messages


def _plan_result_from_tool_call(tc: Any, query: str) -> AgentPlanResult | None:
    tool_name = tc.function.name

    if tool_name not in ALLOWED_TOOLS:
        logger.info("模型选择了未知工具 '{}'，回退本地规则", tool_name)
        _fail_plan("模型选择了未知工具")
        return None

    try:
        raw_args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        logger.info("模型工具参数非 JSON，回退本地规则: {}", str(e)[:80])
        _fail_plan("模型工具参数非 JSON")
        return None

    schema = TOOL_ARGS_SCHEMA[tool_name]
    try:
        validated = schema(**raw_args)
    except Exception as e:
        logger.info("工具参数校验失败（{}），回退本地规则: {}", tool_name, str(e)[:120])
        _fail_plan("模型工具参数校验失败")
        return None

    return _to_plan_result(tool_name, validated, query)


def _to_react_decision(resp: Any, query: str) -> AgentReactDecision | None:
    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        plan = _plan_result_from_tool_call(tool_calls[0], query)
        if plan is None:
            return None
        return AgentReactDecision(
            kind="action",
            public_reason=plan.reasoning,
            plan=plan,
        )

    content = (getattr(msg, "content", "") or "").strip()
    if not content:
        _fail_plan("模型未选择工具且未给出最终回答")
        return None

    final_answer = content
    public_reason = "模型基于已有观察生成最终回答。"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            final_answer = str(parsed.get("final_answer") or parsed.get("answer") or content).strip()
            public_reason = str(parsed.get("public_reason") or public_reason).strip()
    except json.JSONDecodeError:
        pass
    if not final_answer:
        _fail_plan("模型最终回答为空")
        return None
    return AgentReactDecision(
        kind="final",
        public_reason=public_reason,
        final_answer=final_answer[:2000],
    )


def _to_plan_result(
    tool_name: str,
    args: BaseModel,
    query: str,
) -> AgentPlanResult:
    label = TOOL_LABELS[tool_name]

    if tool_name == "stock_screen":
        args: StockScreenArgs
        conditions = _normalize_model_conditions_for_query(
            query,
            [
                FilterCondition(field=c.field, op=c.op, value=c.value)
                for c in args.conditions
            ],
        )
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="AI 将自然语言目标转换为结构化筛选条件。",
            conditions=conditions,
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

    if tool_name == "sort_results":
        args: SortResultsArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="用户要求调整上一轮结果排序，沿用上下文条件。",
            sort_by=args.sort_by,
            sort_desc=args.sort_desc,
        )

    if tool_name == "paginate_results":
        args: PaginateResultsArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="用户要求查看上一轮结果的下一批，沿用上下文条件。",
            limit=args.limit,
        )

    if tool_name == "stock_detail":
        args: StockDetailArgs
        return AgentPlanResult(
            tool=tool_name,
            tool_label=label,
            reasoning="用户要求查看某只股票详情，定位详情页目标。",
            extra={"code": args.code, "name": args.name},
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


def _normalize_model_conditions_for_query(query: str, conditions: list[FilterCondition]) -> list[FilterCondition]:
    """Clamp over-broad model condition expansions while preserving tool choice."""
    normalized_query = query.replace(" ", "")
    explicit_profit_positive = (
        any(term in normalized_query for term in PROFIT_YOY_TERMS)
        and any(term in normalized_query for term in POSITIVE_GROWTH_TERMS)
    )
    explicit_revenue_positive = (
        any(term in normalized_query for term in REVENUE_YOY_TERMS)
        and any(term in normalized_query for term in POSITIVE_GROWTH_TERMS)
    )
    if not explicit_profit_positive and not explicit_revenue_positive:
        return conditions

    mentions_revenue_yoy = any(term in normalized_query for term in REVENUE_YOY_TERMS)
    normalized: list[FilterCondition] = []
    for condition in conditions:
        if condition.field == "revenue_yoy" and not mentions_revenue_yoy:
            continue
        if condition.field == "revenue_yoy" and explicit_revenue_positive and condition.op in {"gt", "gte"}:
            value = condition.value
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 20:
                normalized.append(FilterCondition(field="revenue_yoy", op="gt", value=0))
                continue
        if condition.field == "profit_yoy" and condition.op in {"gt", "gte"}:
            value = condition.value
            if explicit_profit_positive and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 20:
                normalized.append(FilterCondition(field="profit_yoy", op="gt", value=0))
                continue
        normalized.append(condition)
    return normalized
