from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from statistics import mean
import time
from typing import Any

from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.models.stock import StockBasic, StockDaily
from app.schemas.screener import FilterCondition, ScreenRequest
from app.schemas.strategy import (
    StrategyAgentPlan,
    StrategyAgentResponse,
    StrategyPickItem,
    StrategySelectResponse,
    StrategyTemplate,
    StrategyToolCall,
    StrategyToolField,
    StrategyToolInfo,
)
from app.services import qwen_client, screener_engine


TEMPLATES = [
    StrategyTemplate(
        id="turtle_breakout",
        name="海龟突破",
        tag="突破",
        description="参考 Sequoia-X TurtleTrade：突破 20 日高点，成交额过亿，且当日阳线真涨。",
        rules=["收盘价突破前 20 日最高价", "成交额大于 1 亿元", "收盘价高于开盘价和昨日收盘价"],
    ),
    StrategyTemplate(
        id="ma_volume",
        name="均线放量",
        tag="趋势",
        description="参考 Sequoia-X MaVolume：5 日均线上穿 20 日均线，并有成交量放大确认。",
        rules=["5 日均线上穿 20 日均线", "成交量大于 20 日均量 1.5 倍", "按放量强度和涨幅排序"],
    ),
    StrategyTemplate(
        id="rps_breakout",
        name="RPS 强势突破",
        tag="强势",
        description="参考 Sequoia-X RpsBreakout：120 日涨幅横向排名靠前，且价格接近阶段高点。",
        rules=["120 日涨幅排名进入前 10%", "收盘价接近 120 日最高价", "优先选择相对强度更高的股票"],
    ),
    StrategyTemplate(
        id="high_tight_flag",
        name="高位窄幅整理",
        tag="形态",
        description="参考 Sequoia-X HighTightFlag：先强势上涨，再高位缩量窄幅整理。",
        rules=["40 日内最高/最低涨幅大于 60%", "近 10 日振幅小于 15%", "近 10 日仍处于 40 日高点附近", "当日成交量缩至 20 日均量 60% 以下"],
    ),
]

TEMPLATE_MAP = {tpl.id: tpl for tpl in TEMPLATES}
_RESULT_CACHE: dict[tuple[str, int], tuple[float, StrategySelectResponse]] = {}
_RESULT_CACHE_TTL = 300
_AI_STATUS_CACHE: tuple[float, dict] | None = None
_AI_STATUS_TTL = 120


@dataclass
class DailyPoint:
    code: str
    name: str | None
    industry: str | None
    market: str | None
    trade_date: object
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None


def list_templates() -> list[StrategyTemplate]:
    return TEMPLATES


def list_agent_tools() -> list[StrategyToolInfo]:
    return [
        StrategyToolInfo(
            id="strategy_design",
            label="策略设计",
            category="规划工具",
            description="当用户只要求设计选股思路、列出量化条件或解释策略框架时使用；只返回条件建议，不执行股票筛选。",
            inputs=["query"],
            outputs=["策略框架", "量化条件", "执行注意事项"],
            examples=["帮我设计一个稳健的选股策略，列出量化条件", "只列一个低估值高质量策略，不要筛股票"],
            fields=_tool_fields(),
            data_notes=[
                "该工具不调用 screener_engine，不返回股票池。",
                "量化条件是策略草案，执行前需要根据行业和数据覆盖率调整阈值。",
            ],
        ),
        StrategyToolInfo(
            id="stock_screen",
            label="结构化股票筛选",
            category="基础工具",
            description="把自然语言目标转换为字段条件，再调用 screener_engine.screen 查询本地最新行情、估值和财务表。",
            inputs=["conditions", "logic", "sort_by", "limit"],
            outputs=["股票代码", "名称", "行业", "现价", "估值", "市值", "命中条件"],
            examples=["低估值高分红的银行股", "半导体行业里的大市值龙头", "白马股，ROE 高，估值不要太贵"],
            fields=_tool_fields(),
            data_notes=[
                "行情字段来自本地 stock_daily 最新交易日。",
                "ROE、营收同比、净利润同比等来自本地 StockFinancial 最新报告期。",
                "字段缺失时对应条件不会命中，前端展示为缺失而不是补假数据。",
            ],
        ),
        StrategyToolInfo(
            id="industry_match",
            label="行业关键词匹配",
            category="参数工具",
            description="把用户口语里的行业或主题词扩展为本地行业字段可识别的关键词。",
            inputs=["query", "industry_terms"],
            outputs=["industry 条件"],
            examples=["大消费", "新能源车", "TMT", "半导体"],
            fields=[field for field in _tool_fields() if field.key == "industry"],
            data_notes=["只负责生成行业条件，不直接返回股票池。"],
        ),
        StrategyToolInfo(
            id="result_sort",
            label="结果排序",
            category="参数工具",
            description="基于用户要求或上一轮上下文选择排序字段和方向，再交给筛选工具执行。",
            inputs=["sort_by", "sort_desc"],
            outputs=["排序参数"],
            examples=["按股息率排序", "按市值降序", "换一批"],
            fields=[
                field for field in _tool_fields()
                if field.key in {"pe", "pb", "roe", "market_cap", "dividend_yield", "close", "turnover"}
            ],
            data_notes=["排序在后端筛选引擎分页前执行，避免只排序当前页。"],
        ),
        StrategyToolInfo(
            id="strategy_select",
            label="策略选股",
            category="策略工具",
            description="执行项目内置选股策略，当前策略参考 Sequoia-X 思路改写为本地日线实时计算。",
            inputs=["strategy_id", "limit"],
            outputs=["策略得分", "命中信号", "关键指标", "交易日"],
            examples=[tpl.name for tpl in TEMPLATES],
            data_notes=[
                "当前策略只做选股，不做收益回测。",
                "策略依赖日线 OHLCV；数据不足的股票会被跳过。",
                "结果表示当前条件命中，不构成买卖建议。",
            ],
        ),
        StrategyToolInfo(
            id="explain_result",
            label="结果解释",
            category="对话工具",
            description="当用户追问上一轮结果为什么命中、怎么看某只股票时使用；只解释当前结果，不重新筛选。",
            inputs=["query", "last_result"],
            outputs=["命中原因", "关键指标解释", "风险提示"],
            examples=["为什么这些股票会被选出来？", "第一只怎么样？", "这个结果怎么看"],
            data_notes=["依赖前端传回的上一轮结果；上下文为空时会转为补充追问。"],
        ),
        StrategyToolInfo(
            id="stock_detail",
            label="个股详情",
            category="对话工具",
            description="当用户明确要求查看某只股票详情时使用；只定位详情页目标，不重新筛选。",
            inputs=["query", "last_result"],
            outputs=["股票代码", "详情页路径"],
            examples=["查看第一只详情", "打开招商银行详情", "看 600036.SH 详情"],
            data_notes=["依赖用户输入的股票代码/名称或上一轮结果顺序；不会调用 screener_engine。"],
        ),
        StrategyToolInfo(
            id="ask_clarification",
            label="补充追问",
            category="对话工具",
            description="当用户需求过于模糊时使用，先询问风险偏好、行业、周期或指标侧重点，不硬套默认条件。",
            inputs=["query"],
            outputs=["澄清问题", "可选方向"],
            examples=["帮我选点好股票", "推荐几个股票", "有什么可以买"],
            data_notes=["该工具不调用 screener_engine，也不返回股票池。"],
        ),
    ]


def run_strategy_selection(db: Session, strategy_id: str, limit: int = 50) -> StrategySelectResponse:
    if strategy_id not in TEMPLATE_MAP:
        raise ValueError(f"未知策略: {strategy_id}")

    cache_key = (strategy_id, limit)
    cached = _RESULT_CACHE.get(cache_key)
    if cached and time.monotonic() < cached[0]:
        return cached[1]

    history_days = {
        "turtle_breakout": 35,
        "ma_volume": 35,
        "rps_breakout": 130,
        "high_tight_flag": 55,
    }[strategy_id]
    histories = _load_histories(db, days=history_days)
    evaluator = {
        "turtle_breakout": _eval_turtle_breakout,
        "ma_volume": _eval_ma_volume,
        "rps_breakout": _eval_rps_breakout,
        "high_tight_flag": _eval_high_tight_flag,
    }[strategy_id]

    items = evaluator(histories)
    items.sort(key=lambda item: item.score, reverse=True)
    latest_date = max((item.trade_date for item in items if item.trade_date), default=None)
    response = StrategySelectResponse(
        strategy=TEMPLATE_MAP[strategy_id],
        trade_date=latest_date,
        total=len(items),
        items=items[:limit],
        notes=[
            "策略选股只基于本地日线与估值数据做条件筛选，结果表示当前条件命中。",
            "Sequoia-X 原策略以收盘后批处理为主；这里改写为接口实时计算，便于前端查看命中股票。",
        ],
    )
    _RESULT_CACHE[cache_key] = (time.monotonic() + _RESULT_CACHE_TTL, response)
    return response


def _tool_call(
    name: str,
    label: str,
    status: str = "done",
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    message: str = "",
    call_id: str | None = None,
) -> StrategyToolCall:
    return StrategyToolCall(
        id=call_id or name,
        name=name,
        label=label,
        status=status,
        params=params or {},
        result=result or {},
        message=message,
    )


def _planned_tool_calls(plan: StrategyAgentPlan) -> list[StrategyToolCall]:
    calls = [
        _tool_call(
            "tool_router",
            "意图判断",
            result={"tool": plan.tool, "label": plan.tool_label},
            message=plan.reasoning,
        )
    ]
    calls.append(
        _tool_call(
            "parameter_validation",
            "参数校验",
            message=(
                "筛选参数已校验"
                if plan.tool in ("stock_screen", "strategy_select")
                else "请求参数已校验"
            ),
        )
    )
    if plan.tool in ("stock_screen", "strategy_design") and plan.conditions:
        calls.append(
            _tool_call(
                "condition_parser",
                "条件生成",
                result={"conditions": len(plan.conditions), "logic": plan.logic},
                message="已生成结构化条件",
            )
        )
        if any(cond.field == "industry" for cond in plan.conditions):
            calls.append(
                _tool_call(
                    "industry_match",
                    "行业关键词匹配",
                    result={
                        "terms": [
                            term
                            for cond in plan.conditions
                            if cond.field == "industry"
                            for term in (
                                cond.value
                                if isinstance(cond.value, list)
                                else [cond.value]
                            )
                        ]
                    },
                    message="已匹配本地行业关键词",
                )
            )
        if plan.sort_by:
            calls.append(
                _tool_call(
                    "result_sort",
                    "结果排序",
                    params={"sort_by": plan.sort_by, "sort_desc": plan.sort_desc},
                    message="已确定排序参数",
                )
            )
    elif plan.tool == "strategy_select":
        calls.append(
            _tool_call(
                "strategy_template_match",
                "策略模板匹配",
                params={"strategy_id": plan.strategy_id},
                message="已匹配内置策略模板",
            )
        )
    elif plan.tool == "ask_clarification":
        calls.append(
            _tool_call(
                "ask_clarification",
                "补充追问",
                status="skipped",
                message="条件不足，未调用股票筛选",
            )
        )
    elif plan.tool == "explain_result":
        calls.append(
            _tool_call(
                "explain_result",
                "结果解释",
                message="基于上一轮上下文解释结果",
            )
        )
    elif plan.tool == "stock_detail":
        calls.append(
            _tool_call(
                "stock_detail",
                "个股详情",
                message="已定位详情页目标",
            )
        )
    return calls


def _planned_tool_calls_without(plan: StrategyAgentPlan, excluded: set[str]) -> list[StrategyToolCall]:
    return [call for call in _planned_tool_calls(plan)[1:] if call.name not in excluded]


def _mark_model_response(
    response: StrategyAgentResponse,
    model_plan: qwen_client.AgentPlanResult,
) -> StrategyAgentResponse:
    response.plan.ai_configured = True
    response.plan.ai_used = True
    response.plan.reasoning = model_plan.reasoning
    response.tool_trace = ["模型 FC Agent 已选择工具并校验通过", *response.tool_trace]
    if response.plan.tool != "stock_detail":
        response.tool_calls = _planned_tool_calls(response.plan)
    return response


def _build_non_executing_model_response(
    query: str,
    context: dict[str, Any] | None,
    model_plan: qwen_client.AgentPlanResult,
) -> StrategyAgentResponse | None:
    if model_plan.tool == "strategy_design":
        response = build_strategy_design_response(query, ai_configured=True)
        quantitative_conditions = [
            str(item).strip()
            for item in model_plan.extra.get("quantitative_conditions", [])
            if str(item).strip()
        ]
        framework = str(model_plan.extra.get("framework") or "").strip()
        notes = str(model_plan.extra.get("notes") or "").strip()
        if quantitative_conditions:
            response.answer = "\n".join([
                "我先给出策略草案，不执行筛选。",
                "建议量化条件：",
                *[f"{index}. {item}" for index, item in enumerate(quantitative_conditions, start=1)],
                *([f"策略框架：{framework}"] if framework else []),
                *([f"执行注意：{notes}"] if notes else []),
            ])
        return _mark_model_response(response, model_plan)
    if model_plan.tool == "ask_clarification":
        response = build_clarification_response(query, ai_configured=True)
        question = str(model_plan.extra.get("question") or "").strip()
        if question:
            response.answer = question
        return _mark_model_response(response, model_plan)
    if model_plan.tool == "explain_result":
        if is_explain_result_query(query, context):
            response = build_explain_result_response(query, context or {}, ai_configured=True)
        else:
            response = build_missing_context_response(query, ai_configured=True)
        return _mark_model_response(response, model_plan)
    if model_plan.tool == "stock_detail":
        response = build_stock_detail_response(
            query,
            context or {},
            ai_configured=True,
            code=str(model_plan.extra.get("code") or ""),
            name=str(model_plan.extra.get("name") or ""),
        )
        return _mark_model_response(response, model_plan)
    return None


def plan_agent_selection(
    query: str,
    limit: int = 50,
    context: dict[str, Any] | None = None,
) -> StrategyAgentResponse:
    """Build an agent tool plan without executing project-owned tools.

    Model-first: when AI is configured and available, the model FC Agent
    selects the tool and generates structured args.  On any failure the
    local rule Agent takes over as fallback.
    """
    ai_status = _ai_status()
    ai_configured = bool(ai_status.get("configured"))
    ai_available = bool(ai_status.get("ok"))
    warnings: list[str] = []
    tool_trace: list[str] = []

    # Fast local checks for design / clarification when AI is not available
    if not ai_available:
        if is_strategy_design_query(query):
            return build_strategy_design_response(query, ai_configured=ai_configured)
        if is_clarification_query(query):
            return build_clarification_response(query, ai_configured=ai_configured)

    # ── Model FC Agent (primary) ──
    model_plan = None
    if ai_configured and ai_available:
        try:
            model_plan = qwen_client.plan_agent_turn(query, context)
        except Exception as e:
            logger.warning("模型规划异常，已回退本地规则 Agent: {}", str(e)[:120])
            warnings.append("模型规划暂不可用，已回退本地规则 Agent。")

    if model_plan is not None:
        non_executing = _build_non_executing_model_response(query, context, model_plan)
        if non_executing is not None:
            non_executing.warnings = warnings
            return non_executing
        plan = StrategyAgentPlan(
            tool=model_plan.tool,
            tool_label=model_plan.tool_label,
            reasoning=model_plan.reasoning,
            conditions=model_plan.conditions,
            logic=model_plan.logic if model_plan.logic in ("AND", "OR") else "AND",
            sort_by=model_plan.sort_by,
            sort_desc=model_plan.sort_desc,
            limit=min(max(model_plan.limit, 1), 200),
            offset=min(max(model_plan.offset, 0), 10_000),
            strategy_id=model_plan.strategy_id,
            ai_configured=True,
            ai_used=True,
        )
        # Extra guard: implicit empty conditions without explicit all-stock
        if plan.tool == "stock_screen" and not plan.conditions and not is_explicit_all_stocks_query(query):
            warnings.append("模型未返回有效筛选条件，已回退本地规则。")
            plan = _plan_agent_locally(query, limit, ai_configured)
        else:
            tool_trace.append("模型 FC Agent 已选择工具并校验通过")
    else:
        # ── Local rule Agent (fallback) ──
        plan = _plan_agent_locally(query, limit, ai_configured)
        if ai_configured and not ai_available:
            reason = ai_status.get("reason") or "AI 服务不可用"
            warnings.append(f"AI 服务已配置但当前不可用：{reason}。已使用本地规则 Agent 规划。")
        elif ai_configured and ai_available:
            warnings.append("模型未生成有效规划，已回退本地规则 Agent。")
        elif not ai_configured:
            warnings.append("AI 服务未配置，当前使用本地规则 Agent 规划；配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY 后会优先使用 AI 解析。")

    # ── Safety guard ──
    if plan.tool == "stock_screen" and not plan.conditions and not is_explicit_all_stocks_query(query):
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.warnings = [*warnings, "已阻止无条件全市场筛选。"]
        response.tool_trace.append("未调用 screener_engine.screen：空条件筛选需要用户明确要求查看全部股票")
        return response

    plan.condition_labels = _condition_labels(plan.conditions)
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="工具规划完成，等待执行。",
        warnings=warnings,
        tool_trace=tool_trace,
        tool_calls=_planned_tool_calls(plan),
    )


def execute_agent_plan(
    db: Session,
    response: StrategyAgentResponse,
    limit: int = 50,
) -> StrategyAgentResponse:
    """Execute a prepared tool plan and attach the real result."""
    plan = response.plan
    if plan.tool not in ("stock_screen", "strategy_select"):
        return response
    if plan.tool == "stock_screen" and not plan.conditions and not is_explicit_all_stocks_query(response.query):
        guarded = build_clarification_response(response.query, ai_configured=plan.ai_configured)
        guarded.answer = "我还没有拿到可执行的筛选条件。请补充指标、行业或风险偏好后再执行。"
        guarded.warnings = [*response.warnings, "已阻止无条件全市场筛选。"]
        guarded.tool_trace = [
            *response.tool_trace,
            "未调用 screener_engine.screen：空条件筛选需要用户明确要求查看全部股票",
        ]
        guarded.tool_calls = [
            *response.tool_calls,
            _tool_call(
                "stock_screen",
                "股票筛选",
                status="skipped",
                message="空条件筛选已拦截",
            ),
        ]
        return guarded

    effective_limit = min(max(plan.limit, 1), limit)
    warnings = list(response.warnings)
    tool_trace = list(response.tool_trace)
    if plan.tool == "strategy_select":
        strategy_id = plan.strategy_id or "rps_breakout"
        tool_trace.append(f"调用 strategy_selector.run_strategy_selection(strategy_id={strategy_id}, limit={effective_limit})")
        result = run_strategy_selection(db, strategy_id, effective_limit)
        answer = _summarize_strategy_agent(response.query, plan, result.total, [item.name or item.code for item in result.items[:5]])
        return StrategyAgentResponse(
            query=response.query,
            plan=plan,
            strategy_result=result,
            answer=answer,
            warnings=warnings,
            tool_trace=tool_trace,
            tool_calls=[
                *response.tool_calls,
                _tool_call(
                    "strategy_select",
                    "策略选股",
                    result={"total": result.total, "returned": len(result.items), "strategy_id": strategy_id},
                    message="策略选股完成",
                ),
            ],
        )

    req = ScreenRequest(
        conditions=plan.conditions,
        logic=plan.logic if plan.logic in ("AND", "OR") else "AND",
        sort_by=plan.sort_by,
        sort_desc=plan.sort_desc,
        offset=max(plan.offset, 0),
        limit=effective_limit,
    )
    tool_trace.append(f"调用 screener_engine.screen(conditions={len(req.conditions)}, limit={effective_limit})")
    result = screener_engine.screen(db, req)
    page_reset = False
    if is_result_page_query(response.query) and result.total > 0 and not result.items and req.offset >= result.total:
        req = ScreenRequest(
            conditions=plan.conditions,
            logic=req.logic,
            sort_by=req.sort_by,
            sort_desc=req.sort_desc,
            offset=0,
            limit=effective_limit,
        )
        plan.offset = 0
        page_reset = True
        tool_trace.append("结果翻页已到末尾，回到第一批结果")
        result = screener_engine.screen(db, req)
    result.parsed_conditions = req.conditions
    names = [item.name or item.code for item in result.items[:5]]
    answer = _summarize_screen_agent(response.query, plan, result.total, names)
    if page_reset:
        picked = "、".join(names) if names else "暂无命中"
        answer = f"上一轮已经到最后一批，已回到第一批结果。当前共 {result.total} 只，前排结果：{picked}。"
    return StrategyAgentResponse(
        query=response.query,
        plan=plan,
        screen_result=result,
        answer=answer,
        warnings=warnings,
        tool_trace=tool_trace,
        tool_calls=[
            *response.tool_calls,
            *(
                [
                    _tool_call(
                        "result_pagination_reset",
                        "结果分页",
                        params={"offset": 0, "limit": req.limit},
                        message="下一批已到末尾，回到第一批结果",
                    )
                ]
                if page_reset
                else []
            ),
            _tool_call(
                "stock_screen",
                "股票筛选",
                result={"total": result.total, "returned": len(result.items), "offset": req.offset, "limit": req.limit},
                message="股票筛选完成",
            ),
        ],
    )


def run_agent_selection(db: Session, query: str, limit: int = 50) -> StrategyAgentResponse:
    """Plan and execute one agent-style stock-selection turn."""
    response = plan_agent_selection(query, limit=limit)
    return execute_agent_plan(db, response, limit=limit)


def preview_chat_plan(
    query: str,
    context: dict[str, Any] | None = None,
    limit: int = 50,
) -> StrategyAgentPlan:
    """Return a fast local routing preview for progressive SSE feedback."""
    context = context or {}
    fast_path = _plan_chat_fast_path(query, context, limit=limit, ai_configured=_ai_configured())
    if fast_path is not None:
        return fast_path.plan
    if is_strategy_design_query(query):
        return build_strategy_design_response(query, ai_configured=_ai_configured()).plan
    return _plan_agent_locally(query, limit, _ai_configured())


def _plan_chat_fast_path(
    query: str,
    context: dict[str, Any],
    *,
    limit: int,
    ai_configured: bool,
) -> StrategyAgentResponse | None:
    """Resolve deterministic chat intents before asking the remote model."""
    if is_adjustment_query(query):
        return build_adjust_conditions_response(query, context, ai_configured=ai_configured)
    if is_result_page_query(query):
        return build_context_page_response(query, context, limit=limit, ai_configured=ai_configured)
    if is_result_sort_query(query):
        return build_context_sort_response(query, context, ai_configured=ai_configured)
    if is_confirmation_query(query):
        return build_context_screen_response(query, context, ai_configured=ai_configured)
    if is_stock_detail_query(query):
        return build_stock_detail_response(query, context, ai_configured=ai_configured)
    if is_result_explanation_query(query):
        if is_explain_result_query(query, context):
            return build_explain_result_response(query, context, ai_configured=ai_configured)
        return build_missing_context_response(query, ai_configured=ai_configured)
    if is_clarification_query(query):
        return build_clarification_response(query, ai_configured=ai_configured)
    return None


def plan_chat_agent(
    query: str,
    context: dict[str, Any] | None = None,
    limit: int = 50,
) -> StrategyAgentResponse:
    """Route and plan a chat turn without executing stock tools."""
    context = context or {}
    ai_configured = _ai_configured()
    fast_path = _plan_chat_fast_path(query, context, limit=limit, ai_configured=ai_configured)
    if fast_path is not None:
        fast_path.tool_trace = ["本地快速路径命中，跳过模型规划", *fast_path.tool_trace]
        return fast_path

    model_fallback: StrategyAgentResponse | None = None
    ai_status = _ai_status()
    if ai_status.get("configured") and ai_status.get("ok"):
        model_fallback = plan_agent_selection(query, limit=limit, context=context)
        if model_fallback.plan.ai_used:
            return model_fallback

    return model_fallback or plan_agent_selection(query, limit=limit, context=context)


def run_chat_agent(
    db: Session,
    query: str,
    context: dict[str, Any] | None = None,
    limit: int = 50,
) -> StrategyAgentResponse:
    """Plan and execute a chat turn with optional previous-result context."""
    response = plan_chat_agent(query, context=context, limit=limit)
    return execute_agent_plan(db, response, limit=limit)


def is_clarification_query(query: str) -> bool:
    """Return True when the user intent is too vague to run a real screen."""
    q = query.strip().lower()
    if not q:
        return True
    if is_confirmation_query(query):
        return True

    normalized = "".join(ch for ch in q if ch not in "，。！？!?、,. ")
    smalltalk_terms = {
        "你好", "您好", "hello", "hi", "嗨", "谢谢", "感谢", "辛苦了",
        "随便聊聊", "聊聊", "在吗", "你是谁",
    }
    if normalized in smalltalk_terms:
        return True

    vague_terms = (
        "帮我选点", "帮我选一些", "帮我选几个", "推荐点", "推荐几个", "推荐一些",
        "有什么股票", "买什么", "可以买", "好股票", "随便选", "来几个",
    )
    if not any(term in q for term in vague_terms):
        return False

    concrete_terms = (
        "低估值", "高分红", "股息", "roe", "pe", "pb", "市盈率", "市净率",
        "成长", "增长", "净利润", "营收", "行业", "银行", "白酒", "半导体",
        "医药", "新能源", "消费", "龙头", "蓝筹", "大盘", "小盘", "突破",
        "强势", "均线", "放量", "海龟", "rps", "%",
    )
    has_number = any(ch.isdigit() for ch in q)
    has_concrete_constraint = has_number or any(term in q for term in concrete_terms)
    return not has_concrete_constraint


def is_confirmation_query(query: str) -> bool:
    """Return True for short follow-up confirmations that require prior context."""
    normalized = "".join(ch for ch in query.strip().lower() if ch not in "，。！？!?、,. ")
    return normalized in {
        "可以", "可以做吧", "可以执行", "做吧", "按这个来", "按这个做",
        "执行吧", "执行", "继续", "继续吧", "开始吧", "就这样", "确认",
        "现在执行", "执行一下", "现在跑", "跑一下",
    }


def is_explicit_all_stocks_query(query: str) -> bool:
    """Allow an empty-condition screen only when the user explicitly asks for it."""
    q = query.strip().lower()
    return any(term in q for term in (
        "全部股票", "所有股票", "全市场股票", "查看全市场", "显示全市场",
        "不设条件", "不限条件", "无条件筛选", "放宽全部条件",
    ))


def is_explain_result_query(query: str, context: dict[str, Any] | None = None) -> bool:
    """Return True when the turn asks to explain the previous result."""
    if not context:
        return False
    if not is_result_explanation_query(query):
        return False
    return bool(_context_items(context) or _context_conditions(context))


def is_result_explanation_query(query: str) -> bool:
    q = query.strip().lower()
    explain_terms = (
        "为什么", "原因", "怎么看", "解释", "说明", "分析一下", "这些股票",
        "这些结果", "这个结果", "第一只", "第一支", "前几个", "命中",
    )
    return any(term in q for term in explain_terms)


def is_adjustment_query(query: str) -> bool:
    q = query.strip().lower()
    return any(term in q for term in (
        "再严格", "严格一点", "更严格", "收紧", "门槛高", "更稳健",
        "放宽", "宽松", "多一点", "扩大范围", "条件松",
    ))


def is_result_sort_query(query: str) -> bool:
    q = query.strip().lower()
    return ("排序" in q or "按" in q or "优先" in q) and _requested_sort_by(query) is not None


def is_result_page_query(query: str) -> bool:
    q = "".join(ch for ch in query.strip().lower() if ch not in "，。！？!?、,. ")
    return q in {"换一批", "下一页", "下页", "再来一批", "继续看", "更多"}


def is_stock_detail_query(query: str) -> bool:
    q = query.strip().lower()
    if _extract_stock_code(query):
        return any(term in q for term in ("详情", "详细", "打开", "查看", "看一下", "看下", "进入"))
    return any(term in q for term in ("详情", "详细资料", "详情页", "打开", "进入"))


def is_strategy_design_query(query: str) -> bool:
    """Return True when the user asks for a strategy plan rather than execution."""
    q = query.strip().lower()
    explicit_design_only = (
        "只列", "只设计", "不要筛", "不筛选", "不用筛",
        "不执行", "不要执行", "别执行", "先别执行", "暂不执行", "先别跑",
    )
    if any(k in q for k in explicit_design_only):
        return True

    design_terms = ("设计", "制定", "列出", "量化条件", "策略框架", "选股策略", "策略思路", "怎么选", "如何选")
    strategy_terms = ("策略", "量化", "条件", "稳健", "选股")
    execution_terms = ("筛选", "筛出", "选出", "找出", "找股票", "推荐股票", "股票池", "命中", "跑一下", "执行")
    has_design_intent = any(k in q for k in design_terms)
    has_strategy_topic = any(k in q for k in strategy_terms)
    has_execution_intent = any(k in q for k in execution_terms)
    return has_design_intent and has_strategy_topic and not has_execution_intent


def build_strategy_design_response(query: str, ai_configured: bool = False) -> StrategyAgentResponse:
    conditions = _strategy_design_conditions(query)
    plan = StrategyAgentPlan(
        tool="strategy_design",
        tool_label="策略设计",
        reasoning="用户请求是设计策略/列量化条件，不是筛出股票；因此只生成条件草案，不调用筛选引擎。",
        conditions=conditions,
        condition_labels=_condition_labels(conditions),
        logic="AND",
        sort_by="roe",
        sort_desc=True,
        ai_configured=ai_configured,
        ai_used=False,
    )
    answer = _summarize_strategy_design(query, plan)
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=answer,
        tool_trace=[
            "tool_router -> strategy_design",
            "跳过 screener_engine.screen：当前请求是策略设计，不是执行选股",
        ],
        tool_calls=_planned_tool_calls(plan),
    )


def build_clarification_response(query: str, ai_configured: bool = False) -> StrategyAgentResponse:
    plan = StrategyAgentPlan(
        tool="ask_clarification",
        tool_label="补充追问",
        reasoning="用户没有给出可执行筛选条件；先询问偏好，避免硬套默认股票池。",
        ai_configured=ai_configured,
        ai_used=False,
    )
    answer = "\n".join([
        "这个需求还不够具体，我先不筛股票。",
        "你更偏向哪一类：低估值高分红、成长股、行业龙头、短线强势，还是低风险蓝筹？",
        "也可以补充行业、持有周期和能接受的波动范围。",
    ])
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=answer,
        tool_trace=[
            "tool_router -> ask_clarification",
            "未调用 screener_engine.screen：缺少风格、行业或指标约束",
        ],
        tool_calls=_planned_tool_calls(plan),
    )


def build_context_screen_response(
    query: str,
    context: dict[str, Any],
    ai_configured: bool = False,
) -> StrategyAgentResponse:
    """Reuse the previous executable conditions for a confirmation turn."""
    conditions = _context_conditions(context)
    if not conditions:
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.answer = "我还没有可以直接执行的上一轮条件。请先描述选股目标，或补充行业和指标偏好。"
        response.tool_trace = [
            "tool_router -> ask_clarification",
            "未调用 screener_engine.screen：确认语缺少可复用的上一轮条件",
        ]
        response.tool_calls = _planned_tool_calls(response.plan)
        return response

    previous_plan = context.get("last_plan") if isinstance(context, dict) else None
    if not isinstance(previous_plan, dict):
        previous_plan = {}
    plan = StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="用户确认执行上一轮方案；沿用对话上下文中的结构化条件调用本地 screener_engine。",
        conditions=conditions,
        condition_labels=_condition_labels(conditions),
        logic=previous_plan.get("logic") if previous_plan.get("logic") in ("AND", "OR") else "AND",
        sort_by=previous_plan.get("sort_by"),
        sort_desc=previous_plan.get("sort_desc") is not False,
        ai_configured=ai_configured,
        ai_used=False,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="已沿用上一轮条件，等待执行。",
        tool_trace=["tool_router -> stock_screen", "沿用上一轮结构化条件"],
        tool_calls=_planned_tool_calls(plan),
    )


def build_adjust_conditions_response(
    query: str,
    context: dict[str, Any],
    ai_configured: bool = False,
) -> StrategyAgentResponse:
    conditions = _context_conditions(context)
    if not conditions:
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.answer = "我还没有上一轮条件可以调整。请先描述一个选股目标。"
        response.tool_trace = [
            "tool_router -> ask_clarification",
            "未调用 screener_engine.screen：缺少可调整的上一轮条件",
        ]
        response.tool_calls = _planned_tool_calls(response.plan)
        return response

    mode = "loose" if any(term in query for term in ("放宽", "宽松", "多一点", "扩大范围", "条件松")) else "strict"
    adjusted = _adjust_conditions(conditions, mode)
    previous_plan = context.get("last_plan") if isinstance(context, dict) else {}
    if not isinstance(previous_plan, dict):
        previous_plan = {}
    plan = StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="用户要求基于上一轮条件调整阈值；先改写条件，再调用本地筛选引擎。",
        conditions=adjusted,
        condition_labels=_condition_labels(adjusted),
        logic=previous_plan.get("logic") if previous_plan.get("logic") in ("AND", "OR") else "AND",
        sort_by=previous_plan.get("sort_by") or _local_sort_by(query, adjusted),
        sort_desc=previous_plan.get("sort_desc") is not False,
        ai_configured=ai_configured,
        ai_used=False,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="已根据上一轮条件调整阈值，等待执行。",
        tool_trace=[
            "tool_router -> stock_screen",
            f"调整上一轮条件：{'放宽' if mode == 'loose' else '收紧'}",
        ],
        tool_calls=[
            _tool_call(
                "tool_router",
                "意图判断",
                result={"tool": "stock_screen", "action": "adjust_conditions"},
                message=plan.reasoning,
            ),
            _tool_call(
                "condition_parser",
                "条件生成",
                params={"mode": "放宽" if mode == "loose" else "收紧"},
                result={"conditions": len(adjusted), "logic": plan.logic},
                message="已改写上一轮条件",
            ),
            *_planned_tool_calls_without(plan, {"condition_parser"}),
        ],
    )


def build_context_sort_response(
    query: str,
    context: dict[str, Any],
    ai_configured: bool = False,
) -> StrategyAgentResponse:
    conditions = _context_conditions(context)
    if not conditions:
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.answer = "我还没有上一轮条件可以排序。请先完成一次筛选。"
        response.tool_trace = [
            "tool_router -> ask_clarification",
            "未调用 screener_engine.screen：缺少可排序的上一轮条件",
        ]
        response.tool_calls = _planned_tool_calls(response.plan)
        return response

    previous_plan = context.get("last_plan") if isinstance(context, dict) else {}
    if not isinstance(previous_plan, dict):
        previous_plan = {}
    sort_by = _requested_sort_by(query) or previous_plan.get("sort_by") or "score"
    plan = StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="用户要求调整上一轮结果排序；沿用条件并修改排序参数后重新筛选。",
        conditions=conditions,
        condition_labels=_condition_labels(conditions),
        logic=previous_plan.get("logic") if previous_plan.get("logic") in ("AND", "OR") else "AND",
        sort_by=sort_by,
        sort_desc=_requested_sort_desc(query, sort_by),
        ai_configured=ai_configured,
        ai_used=False,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="已沿用上一轮条件并调整排序，等待执行。",
        tool_trace=["tool_router -> stock_screen", f"调整排序：{sort_by}"],
        tool_calls=[
            _tool_call(
                "tool_router",
                "意图判断",
                result={"tool": "stock_screen", "action": "result_sort"},
                message=plan.reasoning,
            ),
            _tool_call(
                "result_sort",
                "结果排序",
                params={"sort_by": sort_by, "sort_desc": plan.sort_desc},
                message="已确定排序参数",
            ),
            *_planned_tool_calls_without(plan, {"result_sort"}),
        ],
    )


def build_context_page_response(
    query: str,
    context: dict[str, Any],
    limit: int = 50,
    ai_configured: bool = False,
) -> StrategyAgentResponse:
    conditions = _context_conditions(context)
    if not conditions:
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.answer = "我还没有上一轮结果可以翻页。请先完成一次筛选。"
        response.tool_trace = [
            "tool_router -> ask_clarification",
            "未调用 screener_engine.screen：缺少可翻页的上一轮条件",
        ]
        response.tool_calls = _planned_tool_calls(response.plan)
        return response

    previous_plan = context.get("last_plan") if isinstance(context, dict) else {}
    if not isinstance(previous_plan, dict):
        previous_plan = {}
    last_result = context.get("last_result") if isinstance(context, dict) else {}
    if not isinstance(last_result, dict):
        last_result = {}
    previous_offset = int(last_result.get("offset") or previous_plan.get("offset") or 0)
    previous_limit = int(last_result.get("limit") or limit)
    next_offset = previous_offset + max(previous_limit, 1)
    plan = StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="用户要求查看下一批结果；沿用上一轮条件并移动分页偏移。",
        conditions=conditions,
        condition_labels=_condition_labels(conditions),
        logic=previous_plan.get("logic") if previous_plan.get("logic") in ("AND", "OR") else "AND",
        sort_by=previous_plan.get("sort_by") or "score",
        sort_desc=previous_plan.get("sort_desc") is not False,
        offset=next_offset,
        ai_configured=ai_configured,
        ai_used=False,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="已沿用上一轮条件，准备查看下一批结果。",
        tool_trace=["tool_router -> stock_screen", f"结果翻页：offset={next_offset}"],
        tool_calls=[
            _tool_call(
                "tool_router",
                "意图判断",
                result={"tool": "stock_screen", "action": "next_page"},
                message=plan.reasoning,
            ),
            _tool_call(
                "result_sort",
                "结果分页",
                params={"offset": next_offset, "limit": limit},
                message="已确定下一批结果范围",
            ),
            *_planned_tool_calls_without(plan, {"result_sort"}),
        ],
    )


def build_stock_detail_response(
    query: str,
    context: dict[str, Any],
    ai_configured: bool = False,
    *,
    code: str = "",
    name: str = "",
) -> StrategyAgentResponse:
    target = _resolve_stock_detail_target(query, context, code=code, name=name)
    if not target:
        response = build_clarification_response(query, ai_configured=ai_configured)
        response.answer = "我还没有定位到要查看的股票。可以说“查看第一只详情”，或直接输入股票代码，例如“查看 600036.SH 详情”。"
        response.tool_trace = [
            "tool_router -> ask_clarification",
            "未打开详情页：缺少股票代码、名称或上一轮结果",
        ]
        response.tool_calls = _planned_tool_calls(response.plan)
        return response

    target_name = target.get("name") or target["code"]
    detail_url = f"/detail/{target['code']}"
    plan = StrategyAgentPlan(
        tool="stock_detail",
        tool_label="个股详情",
        reasoning="用户要求查看某只股票详情；基于输入或上一轮结果定位详情页，不重新筛选。",
        ai_configured=ai_configured,
        ai_used=False,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=f"已定位 {target_name}（{target['code']}）的详情页。",
        tool_trace=[
            "tool_router -> stock_detail",
            f"返回详情页目标：{target['code']}，未重新筛选",
        ],
        tool_calls=[
            _tool_call(
                "tool_router",
                "意图判断",
                result={"tool": "stock_detail", "label": "个股详情"},
                message=plan.reasoning,
            ),
            _tool_call(
                "parameter_validation",
                "参数校验",
                message="详情页目标已校验",
            ),
            _tool_call(
                "stock_detail",
                "个股详情",
                result={"code": target["code"], "name": target.get("name"), "url": detail_url},
                message="已定位详情页目标",
            ),
        ],
    )


def build_missing_context_response(query: str, ai_configured: bool = False) -> StrategyAgentResponse:
    plan = StrategyAgentPlan(
        tool="ask_clarification",
        tool_label="补充追问",
        reasoning="用户在追问结果，但当前对话没有可解释的上一轮股票池。",
        ai_configured=ai_configured,
        ai_used=False,
    )
    answer = "\n".join([
        "我这里还没有可解释的上一轮股票结果。",
        "你可以先说一个筛选目标，比如“低估值高分红的银行股”，得到结果后再问为什么命中。",
    ])
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=answer,
        tool_trace=[
            "tool_router -> ask_clarification",
            "未调用筛选工具：当前没有上一轮股票池可解释",
        ],
        tool_calls=_planned_tool_calls(plan),
    )


def build_explain_result_response(
    query: str,
    context: dict[str, Any],
    ai_configured: bool = False,
) -> StrategyAgentResponse:
    conditions = _context_conditions(context)
    items = _context_items(context)
    if not items and not conditions:
        return build_clarification_response(query, ai_configured=ai_configured)

    labels = _condition_labels(conditions)
    previous_plan = _context_plan(context)
    sort_by = previous_plan.get("sort_by") or _context_sort_by(context)
    sort_desc = previous_plan.get("sort_desc")
    if sort_desc is None:
        sort_desc = True
    plan = StrategyAgentPlan(
        tool="explain_result",
        tool_label="结果解释",
        reasoning="用户在追问上一轮结果；基于当前上下文解释，不重新调用筛选工具。",
        conditions=conditions,
        condition_labels=labels,
        ai_configured=ai_configured,
        ai_used=False,
    )
    lines = ["我基于上一轮结果解释，不重新筛选。"]
    lines.append("排序依据：" + _format_sort_basis(sort_by, bool(sort_desc)))
    if labels:
        lines.append("主要命中条件：" + "；".join(labels[:6]))
    if items:
        lines.append("前排股票的关键优势：")
        for item in items[:5]:
            lines.append(f"- {_explain_item(item)}")
        if conditions:
            lines.append("条件对应关系：")
            for item in items[:3]:
                lines.append(f"- {_condition_mapping_for_item(item, conditions)}")
        risks = _explain_result_risks(items, conditions)
        if risks:
            lines.append("可能风险点：" + "；".join(risks[:4]))
    else:
        lines.append("上一轮没有命中股票，通常是条件过严或本地数据缺字段导致。")

    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="\n".join(lines),
        tool_trace=[
            "tool_router -> explain_result",
            "基于上一轮结果生成解释，未重新筛选",
        ],
        tool_calls=_planned_tool_calls(plan),
    )


def is_ai_configured() -> bool:
    return _ai_configured()


def _ai_configured() -> bool:
    if (settings.ai_backend or "openai").lower() == "dashscope":
        return bool(settings.dashscope_api_key)
    return bool(settings.openai_api_key)


def _ai_status() -> dict:
    global _AI_STATUS_CACHE
    configured = _ai_configured()
    if not configured:
        return {"configured": False, "ok": False, "reason": "未配置 AI 服务凭证"}

    now = time.monotonic()
    if _AI_STATUS_CACHE and now < _AI_STATUS_CACHE[0]:
        cached = dict(_AI_STATUS_CACHE[1])
        cached["configured"] = True
        return cached

    status = qwen_client.probe_health()
    status["configured"] = True
    _AI_STATUS_CACHE = (now + _AI_STATUS_TTL, status)
    return status


def _plan_agent_locally(query: str, limit: int, ai_configured: bool) -> StrategyAgentPlan:
    text = query.lower()
    if is_explicit_all_stocks_query(query):
        return StrategyAgentPlan(
            tool="stock_screen",
            tool_label="结构化股票筛选",
            reasoning="用户明确要求查看全部股票，允许执行无条件全市场查询。",
            conditions=[],
            logic="AND",
            sort_by="market_cap",
            sort_desc=True,
            ai_configured=ai_configured,
        )
    if any(k in query for k in ("海龟", "突破", "新高")) or "breakout" in text:
        return StrategyAgentPlan(
            tool="strategy_select",
            tool_label="策略选股",
            reasoning="用户目标偏向突破交易，选择海龟突破策略。",
            strategy_id="turtle_breakout",
            ai_configured=ai_configured,
        )
    if any(k in query for k in ("均线", "放量", "金叉")):
        return StrategyAgentPlan(
            tool="strategy_select",
            tool_label="策略选股",
            reasoning="用户目标偏向趋势确认，选择均线放量策略。",
            strategy_id="ma_volume",
            ai_configured=ai_configured,
        )
    if any(k in query for k in ("rps", "强势", "相对强度")):
        return StrategyAgentPlan(
            tool="strategy_select",
            tool_label="策略选股",
            reasoning="用户目标偏向相对强势股票，选择 RPS 强势突破策略。",
            strategy_id="rps_breakout",
            ai_configured=ai_configured,
        )
    if any(k in query for k in ("高位", "窄幅", "缩量", "旗形", "整理")):
        return StrategyAgentPlan(
            tool="strategy_select",
            tool_label="策略选股",
            reasoning="用户目标偏向形态整理，选择高位窄幅整理策略。",
            strategy_id="high_tight_flag",
            ai_configured=ai_configured,
        )

    conditions = _local_conditions(query)
    return StrategyAgentPlan(
        tool="stock_screen",
        tool_label="结构化股票筛选",
        reasoning="用户目标更像基本面/条件筛选，调用本地 screener_engine。",
        conditions=conditions,
        logic="AND",
        sort_by=_local_sort_by(query, conditions),
        sort_desc=True,
        ai_configured=ai_configured,
    )


def _local_conditions(query: str) -> list[FilterCondition]:
    conditions: list[FilterCondition] = []

    if any(k in query for k in ("低估值", "便宜", "估值低")):
        conditions.extend([
            FilterCondition(field="pe", op="lt", value=15),
            FilterCondition(field="pb", op="lt", value=2),
        ])
    if any(k in query for k in ("高分红", "股息", "分红")):
        conditions.append(FilterCondition(field="dividend_yield", op="gt", value=3))
    if any(k in query for k in ("成长", "高增长")):
        conditions.extend([
            FilterCondition(field="revenue_yoy", op="gt", value=20),
            FilterCondition(field="profit_yoy", op="gt", value=20),
        ])
    if any(k in query for k in ("白马", "优质")):
        conditions.extend([
            FilterCondition(field="roe", op="gt", value=15),
            FilterCondition(field="market_cap", op="gt", value=500),
        ])
    if "小盘" in query:
        conditions.append(FilterCondition(field="market_cap", op="lt", value=100))
    if "中盘" in query:
        conditions.append(FilterCondition(field="market_cap", op="between", value=[100, 500]))
    if any(k in query for k in ("大盘", "蓝筹", "龙头")):
        conditions.append(FilterCondition(field="market_cap", op="gt", value=500))

    industry_terms = [
        "银行", "白酒", "半导体", "光伏", "医药", "新能源", "新能源车", "汽车",
        "消费", "金融", "证券", "保险", "军工", "家电", "食品饮料", "传媒", "软件",
    ]
    matched = [term for term in industry_terms if term in query]
    if matched:
        conditions.append(FilterCondition(field="industry", op="in", value=matched))

    return conditions


def _strategy_design_conditions(query: str) -> list[FilterCondition]:
    """Draft quantitative conditions for strategy-design requests.

    These are not executed directly. They are intentionally conservative and
    use only fields the local screener already understands, so the user can run
    them later after adjusting thresholds.
    """
    conditions = [
        FilterCondition(field="roe", op="gte", value=15),
        FilterCondition(field="debt_ratio", op="lte", value=60),
        FilterCondition(field="gross_margin", op="gte", value=25),
        FilterCondition(field="profit_yoy", op="gte", value=10),
        FilterCondition(field="pe", op="between", value=[0, 25]),
        FilterCondition(field="pb", op="between", value=[0, 3]),
        FilterCondition(field="market_cap", op="gte", value=100),
    ]
    if any(k in query for k in ("分红", "股息", "股息率")):
        conditions.append(FilterCondition(field="dividend_yield", op="gte", value=3))
    if any(k in query for k in ("成长", "增长")):
        conditions.append(FilterCondition(field="revenue_yoy", op="gte", value=10))
    return conditions


def _local_sort_by(query: str, conditions: list[FilterCondition]) -> str | None:
    if any(k in query for k in ("高分红", "股息", "分红")):
        return "dividend_yield"
    if any(k in query for k in ("成长", "增长")):
        return "profit_yoy"
    if any(k in query for k in ("大盘", "龙头", "蓝筹")):
        return "market_cap"
    if any(c.field == "roe" for c in conditions):
        return "roe"
    return "market_cap"


def _requested_sort_by(query: str) -> str | None:
    q = query.strip().lower()
    mapping = [
        (("综合分", "评分", "得分"), "score"),
        (("股息", "分红"), "dividend_yield"),
        (("roe", "盈利", "质量"), "roe"),
        (("pe", "市盈率", "估值"), "pe"),
        (("pb", "市净率"), "pb"),
        (("市值", "规模", "龙头"), "market_cap"),
        (("涨跌幅", "涨幅", "强势"), "change_pct"),
        (("价格", "现价", "收盘价"), "close"),
        (("换手", "活跃"), "turnover"),
    ]
    for terms, field in mapping:
        if any(term in q for term in terms):
            return field
    return None


def _requested_sort_desc(query: str, sort_by: str | None) -> bool:
    q = query.strip().lower()
    if any(term in q for term in ("升序", "从低到高", "最低", "最小", "低到高")):
        return False
    if any(term in q for term in ("降序", "从高到低", "最高", "最大", "高到低")):
        return True
    return sort_by not in {"pe", "pb"}


def _adjust_conditions(conditions: list[FilterCondition], mode: str) -> list[FilterCondition]:
    tighten = mode != "loose"
    adjusted: list[FilterCondition] = []
    lower_is_better = {"pe", "pb", "debt_ratio"}
    higher_is_better = {
        "roe", "dividend_yield", "market_cap", "revenue_yoy",
        "profit_yoy", "gross_margin", "turnover",
    }
    for cond in conditions:
        if cond.field in lower_is_better:
            adjusted.append(_adjust_lower_better(cond, tighten))
        elif cond.field in higher_is_better:
            adjusted.append(_adjust_higher_better(cond, tighten))
        else:
            adjusted.append(cond)
    return adjusted


def _round_threshold(value: float | int) -> float | int:
    rounded = round(float(value), 2)
    return int(rounded) if rounded.is_integer() else rounded


def _adjust_lower_better(cond: FilterCondition, tighten: bool) -> FilterCondition:
    factor = 0.8 if tighten else 1.25
    if cond.op in ("lt", "lte") and isinstance(cond.value, (int, float)):
        return FilterCondition(field=cond.field, op=cond.op, value=_round_threshold(cond.value * factor))
    if cond.op == "between" and isinstance(cond.value, list) and len(cond.value) == 2:
        low, high = cond.value
        if isinstance(high, (int, float)):
            high = _round_threshold(high * factor)
        return FilterCondition(field=cond.field, op=cond.op, value=[low, high])
    return cond


def _adjust_higher_better(cond: FilterCondition, tighten: bool) -> FilterCondition:
    factor = 1.15 if tighten else 0.85
    if cond.op in ("gt", "gte") and isinstance(cond.value, (int, float)):
        return FilterCondition(field=cond.field, op=cond.op, value=_round_threshold(cond.value * factor))
    if cond.op == "between" and isinstance(cond.value, list) and len(cond.value) == 2:
        low, high = cond.value
        if isinstance(low, (int, float)):
            low = _round_threshold(low * factor)
        return FilterCondition(field=cond.field, op=cond.op, value=[low, high])
    return cond


def _summarize_strategy_agent(query: str, plan: StrategyAgentPlan, total: int, names: list[str]) -> str:
    picked = "、".join(names) if names else "暂无命中"
    return f"我将「{query}」规划为「{plan.tool_label}」工具，执行 {plan.strategy_id} 策略。当前命中 {total} 只，前排结果：{picked}。"


def _summarize_screen_agent(query: str, plan: StrategyAgentPlan, total: int, names: list[str]) -> str:
    picked = "、".join(names) if names else "暂无命中"
    if is_confirmation_query(query):
        return f"已按上一轮策略条件执行筛选，当前命中 {total} 只，前排结果：{picked}。"
    if is_result_page_query(query):
        if total == 0:
            return "已沿用上一轮条件查看下一批结果，当前没有命中股票。"
        if plan.offset >= total or not names:
            return f"已沿用上一轮条件查看下一批结果，当前共 {total} 只，已经没有更多结果。"
        start = plan.offset + 1 if total else plan.offset
        end = min(plan.offset + plan.limit, total) if total else plan.offset
        return f"已沿用上一轮条件查看下一批结果，当前共 {total} 只，返回第 {start}–{end} 条：{picked}。"
    if is_result_sort_query(query):
        return f"已沿用上一轮条件并调整排序，当前命中 {total} 只，前排结果：{picked}。"
    if is_adjustment_query(query):
        return f"已基于上一轮条件调整阈值并重新筛选，当前命中 {total} 只，前排结果：{picked}。"
    if is_explicit_all_stocks_query(query) and not plan.conditions:
        return f"已按你的要求展示全市场股票，当前共 {total} 只，前排结果：{picked}。"
    return f"我将「{query}」转换为 {len(plan.conditions)} 个结构化条件，并调用本地筛选引擎。当前命中 {total} 只，前排结果：{picked}。"


def _summarize_strategy_design(query: str, plan: StrategyAgentPlan) -> str:
    lines = [
        f"我判断「{query}」是策略设计请求，先不执行筛选。",
        "建议量化条件：",
        *[f"{idx}. {label}" for idx, label in enumerate(plan.condition_labels, start=1)],
        "执行建议：先用这些条件做初筛，再按行业放宽阈值；银行、保险等金融行业不适合直接套用毛利率和资产负债率。",
    ]
    return "\n".join(lines)


def _context_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = context.get("last_result") if isinstance(context, dict) else None
    if not isinstance(result, dict):
        result = context
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _extract_stock_code(text: str) -> str | None:
    match = re.search(r"(?i)\b(?:(sh|sz|bj)\s*)?(\d{6})(?:\s*[.。]\s*(sh|sz|bj))?\b", text or "")
    if not match:
        return None
    prefix, digits, suffix = match.groups()
    market = (suffix or prefix or "").upper()
    if not market:
        if digits.startswith(("4", "8")):
            market = "BJ"
        else:
            market = "SH" if digits.startswith(("5", "6", "9")) else "SZ"
    return f"{digits}.{market}"


def _detail_ordinal_index(query: str) -> int | None:
    q = "".join(ch for ch in query.strip().lower() if ch not in "，。！？!?、,. ")
    mapping = [
        (("第一只", "第一支", "第一个", "第一家", "第一"), 0),
        (("第二只", "第二支", "第二个", "第二家", "第二"), 1),
        (("第三只", "第三支", "第三个", "第三家", "第三"), 2),
        (("第四只", "第四支", "第四个", "第四家", "第四"), 3),
        (("第五只", "第五支", "第五个", "第五家", "第五"), 4),
    ]
    for terms, index in mapping:
        if any(term in q for term in terms):
            return index
    return None


def _resolve_stock_detail_target(
    query: str,
    context: dict[str, Any],
    *,
    code: str = "",
    name: str = "",
) -> dict[str, Any] | None:
    items = _context_items(context)
    requested_code = _extract_stock_code(code) or _extract_stock_code(query)
    if requested_code:
        for item in items:
            if str(item.get("code") or "").upper() == requested_code:
                return {"code": requested_code, "name": item.get("name")}
        return {"code": requested_code, "name": name or None}

    requested_name = (name or "").strip()
    if not requested_name:
        for item in items:
            item_name = str(item.get("name") or "").strip()
            if item_name and item_name in query:
                requested_name = item_name
                break
    if requested_name:
        for item in items:
            item_name = str(item.get("name") or "").strip()
            if item_name and (requested_name in item_name or item_name in requested_name):
                item_code = str(item.get("code") or "").upper()
                if item_code:
                    return {"code": item_code, "name": item_name}

    ordinal = _detail_ordinal_index(query)
    if ordinal is not None and 0 <= ordinal < len(items):
        item = items[ordinal]
        item_code = str(item.get("code") or "").upper()
        if item_code:
            return {"code": item_code, "name": item.get("name")}
    return None


def _context_conditions(context: dict[str, Any]) -> list[FilterCondition]:
    result = context.get("last_result") if isinstance(context, dict) else None
    raw = None
    if isinstance(result, dict):
        raw = result.get("parsed_conditions")
    raw = raw or context.get("last_conditions") or context.get("parsed_conditions") or []
    if not isinstance(raw, list):
        return []

    conditions: list[FilterCondition] = []
    for item in raw:
        if isinstance(item, FilterCondition):
            conditions.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            conditions.append(FilterCondition(**item))
        except Exception:
            continue
    return conditions


def _context_plan(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    raw = context.get("last_plan") or context.get("agent_plan") or {}
    return raw if isinstance(raw, dict) else {}


def _context_sort_by(context: dict[str, Any]) -> str | None:
    if not isinstance(context, dict):
        return None
    for raw in (context.get("last_result"), context):
        if isinstance(raw, dict) and isinstance(raw.get("sort_by"), str):
            return raw.get("sort_by")
    return None


def _explain_item(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("code") or "未知股票"
    code = item.get("code") or "—"
    parts = [f"{name}（{code}）"]
    metrics = [
        ("行业", item.get("industry")),
        ("PE", item.get("pe")),
        ("ROE", item.get("roe")),
        ("股息率", item.get("dividend_yield")),
        ("市值", item.get("market_cap")),
    ]
    for label, value in metrics:
        if value is None or value == "":
            continue
        suffix = "%" if label in ("ROE", "股息率") else ("亿" if label == "市值" else "")
        parts.append(f"{label}{_compact_metric(value)}{suffix}")
    return "，".join(parts)


def _format_sort_basis(sort_by: str | None, sort_desc: bool) -> str:
    field_names = _field_labels()
    if not sort_by:
        return "沿用上一轮结果顺序，未检测到明确排序字段。"
    direction = "从高到低" if sort_desc else "从低到高"
    return f"按{field_names.get(sort_by, sort_by)}{direction}排列；排在前面的股票更符合当前排序目标。"


def _condition_mapping_for_item(item: dict[str, Any], conditions: list[FilterCondition]) -> str:
    name = item.get("name") or item.get("code") or "未知股票"
    mappings: list[str] = []
    for cond in conditions[:4]:
        label = _format_condition(cond)
        value = item.get(cond.field)
        if value is None and cond.field == "industry":
            value = item.get("industry")
        if value is None:
            mappings.append(f"{label}：缺字段")
        else:
            mappings.append(f"{label}：当前{_compact_metric(value)}")
    return f"{name}：" + "；".join(mappings)


def _explain_result_risks(items: list[dict[str, Any]], conditions: list[FilterCondition]) -> list[str]:
    risks: list[str] = []
    missing_fields = {
        cond.field
        for cond in conditions
        if any(item.get(cond.field) is None for item in items[:5])
    }
    if missing_fields:
        labels = [_field_labels().get(field, field) for field in sorted(missing_fields)]
        risks.append("部分股票缺少" + "、".join(labels) + "字段，排序和解释需要谨慎")
    if any(_as_float(item.get("pe")) is not None and _as_float(item.get("pe")) < 0 for item in items[:5]):
        risks.append("存在负市盈率，通常代表最近利润为负，不能按低估值简单理解")
    if any(_as_float(item.get("roe")) is not None and _as_float(item.get("roe")) < 0 for item in items[:5]):
        risks.append("存在 ROE 为负的股票，盈利质量风险较高")
    if any(_as_float(item.get("dividend_yield")) == 0 for item in items[:5]):
        risks.append("部分股票股息率为 0，不适合高分红目标")
    if not risks:
        risks.append("当前解释只基于本地最新数据快照，仍需结合公告、行业景气度和财报质量复核")
    return risks


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _compact_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _condition_labels(conditions: list[FilterCondition]) -> list[str]:
    labels = [_format_condition(cond) for cond in conditions]
    return [label for label in labels if label]


def _tool_fields() -> list[StrategyToolField]:
    numeric_ops = ["gt", "gte", "lt", "lte", "between"]
    text_ops = ["eq", "in"]
    fields = [
        ("pe", "市盈率", "number", numeric_ops, "估值指标，越低通常代表估值越便宜，但需结合行业。"),
        ("pb", "市净率", "number", numeric_ops, "估值指标，适合银行、周期等重资产行业参考。"),
        ("roe", "ROE", "number", numeric_ops, "净资产收益率，衡量盈利质量。"),
        ("market_cap", "总市值", "number", numeric_ops, "单位为亿元，用于区分小盘、中盘、大盘或龙头。"),
        ("dividend_yield", "股息率", "number", numeric_ops, "现金分红收益率，字段缺失时不补算。"),
        ("revenue_yoy", "营收同比", "number", numeric_ops, "最新报告期营业收入同比增速。"),
        ("profit_yoy", "净利润同比", "number", numeric_ops, "最新报告期净利润同比增速。"),
        ("gross_margin", "毛利率", "number", numeric_ops, "最新报告期毛利率。"),
        ("debt_ratio", "资产负债率", "number", numeric_ops, "最新报告期资产负债率。"),
        ("industry", "行业", "text", text_ops, "支持常见行业关键词和部分同义词扩展。"),
        ("market", "市场", "text", text_ops, "交易市场或板块字段。"),
        ("close", "收盘价", "number", numeric_ops, "最新交易日收盘价。"),
        ("turnover", "换手率", "number", numeric_ops, "最新交易日换手率。"),
    ]
    return [
        StrategyToolField(
            key=key,
            label=label,
            data_type=data_type,
            operators=ops,
            description=description,
        )
        for key, label, data_type, ops, description in fields
    ]


def _format_condition(cond: FilterCondition) -> str:
    field_names = _field_labels()
    op_names = {
        "gt": "大于",
        "gte": "不低于",
        "lt": "低于",
        "lte": "不高于",
        "eq": "等于",
        "between": "介于",
        "in": "包含",
    }
    field = field_names.get(cond.field, cond.field)
    op = op_names.get(cond.op, cond.op)
    value = _format_condition_value(cond.value)
    return f"{field}{op}{value}"


def _field_labels() -> dict[str, str]:
    return {
        "pe": "市盈率",
        "pb": "市净率",
        "roe": "ROE",
        "market_cap": "总市值",
        "dividend_yield": "股息率",
        "revenue_yoy": "营收同比",
        "profit_yoy": "净利润同比",
        "gross_margin": "毛利率",
        "debt_ratio": "资产负债率",
        "industry": "行业",
        "market": "市场",
        "close": "收盘价",
        "turnover": "换手率",
    }


def _format_condition_value(value) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _load_histories(db: Session, days: int, max_codes: int = 1200) -> dict[str, list[DailyPoint]]:
    latest_date = db.query(StockDaily.trade_date).order_by(desc(StockDaily.trade_date)).limit(1).scalar()
    if latest_date is None:
        return {}

    latest_rows = (
        db.query(StockDaily.code)
        .filter(StockDaily.trade_date == latest_date)
        .order_by(desc(StockDaily.amount))
        .limit(max_codes)
        .all()
    )
    codes = [row[0] for row in latest_rows]
    if not codes:
        return {}

    date_rows = (
        db.query(StockDaily.trade_date)
        .distinct()
        .order_by(desc(StockDaily.trade_date))
        .limit(days)
        .all()
    )
    dates = [r[0] for r in date_rows]
    if not dates:
        return {}

    rows = (
        db.query(StockBasic, StockDaily)
        .join(StockDaily, StockDaily.code == StockBasic.code)
        .filter(StockDaily.code.in_(codes), StockDaily.trade_date.in_(dates))
        .order_by(StockDaily.code.asc(), StockDaily.trade_date.asc())
        .all()
    )
    histories: dict[str, list[DailyPoint]] = defaultdict(list)
    for basic, daily in rows:
        if daily.close is None or daily.high is None or daily.low is None:
            continue
        histories[basic.code].append(
            DailyPoint(
                code=basic.code,
                name=basic.name,
                industry=basic.industry,
                market=basic.market,
                trade_date=daily.trade_date,
                open=daily.open,
                high=daily.high,
                low=daily.low,
                close=daily.close,
                volume=daily.volume,
                amount=daily.amount,
            )
        )
    expected_dates = set(dates)
    return {
        code: points
        for code, points in histories.items()
        if len(points) == len(expected_dates)
        and {point.trade_date for point in points} == expected_dates
    }


def _pct(last: DailyPoint, prev: DailyPoint | None) -> float | None:
    if not prev or not prev.close:
        return None
    return (last.close - prev.close) / prev.close * 100 if last.close is not None else None


def _amount_yi(point: DailyPoint) -> float | None:
    # stock_daily.amount 统一按“元”存储，策略层转换为亿元。
    return point.amount / 1e8 if point.amount is not None else None


def _avg(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return mean(nums) if nums else None


def _base_item(points: list[DailyPoint], score: float, signals: list[str], metrics: dict) -> StrategyPickItem:
    last = points[-1]
    prev = points[-2] if len(points) >= 2 else None
    return StrategyPickItem(
        code=last.code,
        name=last.name,
        industry=last.industry,
        market=last.market,
        trade_date=last.trade_date,
        close=last.close,
        change_pct=_pct(last, prev),
        score=round(max(0, min(100, score)), 2),
        signals=signals,
        metrics={k: round(v, 2) if isinstance(v, float) else v for k, v in metrics.items()},
    )


def _eval_turtle_breakout(histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
    items: list[StrategyPickItem] = []
    for points in histories.values():
        if len(points) < 21:
            continue
        last, prev = points[-1], points[-2]
        if last.close is None or last.open is None or prev.close is None:
            continue
        high20 = max(p.high for p in points[-21:-1] if p.high is not None)
        amount_yi = _amount_yi(last) or 0
        if last.close > high20 and amount_yi >= 1 and last.close > last.open and last.close > prev.close:
            breakout_pct = (last.close / high20 - 1) * 100
            score = 20 + min(50, breakout_pct * 10) + min(30, amount_yi / 3)
            items.append(_base_item(points, score, ["20日新高突破", "成交额过亿", "阳线真涨"], {
                "20日高点": high20,
                "突破幅度%": breakout_pct,
                "成交额(亿)": amount_yi,
            }))
    return items


def _eval_ma_volume(histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
    items: list[StrategyPickItem] = []
    for points in histories.values():
        if len(points) < 21:
            continue
        closes = [p.close for p in points]
        volumes = [p.volume for p in points]
        ma5_prev = _avg(closes[-6:-1])
        ma20_prev = _avg(closes[-21:-1])
        ma5 = _avg(closes[-5:])
        ma20 = _avg(closes[-20:])
        vol20 = _avg(volumes[-21:-1])
        last_vol = points[-1].volume
        if None in (ma5_prev, ma20_prev, ma5, ma20, vol20, last_vol):
            continue
        golden_cross = ma5_prev <= ma20_prev and ma5 > ma20
        volume_ratio = last_vol / vol20 if vol20 else 0
        if golden_cross and volume_ratio >= 1.5:
            score = (ma5 / ma20 - 1) * 100 + volume_ratio * 10
            items.append(_base_item(points, score, ["5日均线上穿20日均线", "成交量放大"], {
                "MA5": ma5,
                "MA20": ma20,
                "量比20日": volume_ratio,
            }))
    return items


def _eval_rps_breakout(histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
    candidates = []
    for code, points in histories.items():
        if len(points) < 121:
            continue
        first = points[-121]
        last = points[-1]
        if not first.close or not last.close:
            continue
        pct120 = (last.close / first.close - 1) * 100
        high120 = max(p.high for p in points[-120:] if p.high is not None)
        near_high = last.close >= high120 * 0.9
        candidates.append((code, points, pct120, high120, near_high))

    if not candidates:
        return []
    sorted_pct = sorted(v[2] for v in candidates)
    items: list[StrategyPickItem] = []
    for _code, points, pct120, high120, near_high in candidates:
        rank = sum(1 for v in sorted_pct if v <= pct120) / len(sorted_pct) * 100
        if rank >= 90 and near_high:
            score = rank * 0.8 + min(100, max(0, pct120)) * 0.2
            items.append(_base_item(points, score, ["120日相对强度前10%", "接近阶段高点"], {
                "RPS": rank,
                "120日涨幅%": pct120,
                "120日高点": high120,
            }))
    return items


def _eval_high_tight_flag(histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
    items: list[StrategyPickItem] = []
    for points in histories.values():
        if len(points) < 40:
            continue
        tail40 = points[-40:]
        tail10 = points[-10:]
        high40 = max(p.high for p in tail40 if p.high is not None)
        low40 = min(p.low for p in tail40 if p.low is not None)
        high10 = max(p.high for p in tail10 if p.high is not None)
        low10 = min(p.low for p in tail10 if p.low is not None)
        vol20 = _avg([p.volume for p in points[-21:-1]])
        last_vol = points[-1].volume
        if not low40 or not low10 or not vol20 or last_vol is None:
            continue
        momentum = high40 / low40
        consolidation = high10 / low10
        high_level = low10 >= high40 * 0.8
        shrink = last_vol < vol20 * 0.6
        if momentum > 1.6 and consolidation < 1.15 and high_level and shrink:
            score = momentum * 30 + (1.15 - consolidation) * 100 + (1 - last_vol / vol20) * 20
            items.append(_base_item(points, score, ["强动量", "高位窄幅整理", "缩量"], {
                "40日高低比": momentum,
                "10日振幅比": consolidation,
                "缩量比例": last_vol / vol20,
            }))
    return items
