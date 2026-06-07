"""Bounded ReAct orchestration for the chat Agent.

The model is allowed to choose one tool at a time.  Project-owned tools are
still validated and executed by the backend, then summarized as observations
for the next step.  Private model reasoning is never returned; only public step
summaries, tool names and timings are exposed.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from loguru import logger
from sqlalchemy.orm import Session

from app.schemas.strategy import StrategyAgentPlan, StrategyAgentResponse
from app.services import qwen_client, strategy_selector

MAX_REACT_STEPS = 4
MAX_REACT_SECONDS = 20.0
EXECUTABLE_TOOLS = {"stock_screen", "strategy_select", "sort_results", "paginate_results"}


def run_chat_react_agent(
    db: Session,
    query: str,
    context: dict[str, Any] | None = None,
    limit: int = 50,
    *,
    max_steps: int = MAX_REACT_STEPS,
    total_timeout_seconds: float = MAX_REACT_SECONDS,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> StrategyAgentResponse:
    """Run one bounded ReAct chat turn and return the final response.

    The model owns intent judgment for chat turns. The backend keeps hard
    safety boundaries: unsupported fields are stopped before execution, and
    project-owned tools only run after schema validation. If the model is
    unavailable or cannot produce a valid action/final answer, this returns a
    non-executing chat response instead of silently screening with local rules.
    """
    context = context or {}
    ai_configured = strategy_selector.is_ai_configured()
    unsupported_preflight = strategy_selector.build_unsupported_metric_preflight_response(
        query,
        ai_configured=ai_configured,
    )
    if unsupported_preflight is not None:
        return _execute_prepared_response(db, unsupported_preflight, limit, [], event_sink=event_sink)

    ai_status = strategy_selector._ai_status()
    if not ai_status.get("configured") or not ai_status.get("ok"):
        reason = "AI 服务未配置"
        if ai_status.get("configured"):
            reason = ai_status.get("reason") or "AI 服务不可用"
            reason = f"AI 服务已配置但当前不可用：{reason}"
        return _non_executing_model_failure_response(query, reason, ai_configured=ai_configured)

    started = time.perf_counter()
    observations: list[dict[str, Any]] = []
    react_events: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    current_response: StrategyAgentResponse | None = None

    for step_index in range(1, max_steps + 1):
        if time.perf_counter() - started > total_timeout_seconds:
            return _finish_or_fallback(
                db,
                query,
                context,
                limit,
                current_response,
                react_events,
                "ReAct 总耗时超过 20 秒",
                event_sink=event_sink,
            )

        model_started = time.perf_counter()
        step_exception_reason: str | None = None
        try:
            decision = qwen_client.plan_react_step(
                query,
                context=context,
                observations=observations,
                step_index=step_index,
            )
        except Exception as exc:
            logger.warning("Agent ReAct step 异常，准备兜底: {}", str(exc)[:120])
            decision = None
            step_exception_reason = "模型 ReAct 异常"
        model_ms = int((time.perf_counter() - model_started) * 1000)
        if decision is None:
            reason = step_exception_reason or qwen_client.last_plan_failure_reason() or "模型 ReAct 未生成有效决策"
            return _finish_or_fallback(
                db,
                query,
                context,
                limit,
                current_response,
                react_events,
                reason,
                model_ms=model_ms,
                event_sink=event_sink,
            )

        if decision.kind == "final":
            final = _apply_final_answer(
                query,
                current_response,
                decision.final_answer,
                decision.public_reason,
                ai_configured=True,
            )
            _append_event(react_events, _event(
                "final",
                step_index,
                tool=final.plan.tool,
                model_ms=model_ms,
                timing_phase="model_final",
                public_summary=decision.public_reason or "模型基于 observation 生成最终回答。",
            ), event_sink)
            final.react_steps = [*react_events]
            return final

        plan = decision.plan
        if plan is None:
            return _finish_or_fallback(
                db,
                query,
                context,
                limit,
                current_response,
                react_events,
                "模型 ReAct action 缺少工具计划",
                model_ms=model_ms,
                event_sink=event_sink,
            )

        action_key = _action_key(plan)
        _append_event(react_events, _event(
            "react_step",
            step_index,
            tool=plan.tool,
            model_ms=model_ms,
            timing_phase="model_action",
            public_summary=decision.public_reason or plan.reasoning,
        ), event_sink)
        if action_key in seen_actions:
            reason = "模型重复调用相同工具参数，已停止以避免重复执行"
            return _finish_or_fallback(
                db,
                query,
                context,
                limit,
                current_response,
                react_events,
                reason,
                event_sink=event_sink,
            )
        seen_actions.add(action_key)

        response = _response_from_model_plan(
            db,
            query,
            context,
            plan,
            step_index=step_index,
        )
        if response.plan.tool not in EXECUTABLE_TOOLS:
            _append_event(react_events, _event(
                "final",
                step_index,
                tool=response.plan.tool,
                timing_phase="local_final",
                public_summary="该工具不需要执行本地筛选，已直接生成回答。",
            ), event_sink)
            response.react_steps = [*react_events]
            return response

        _append_event(react_events, _event(
            "tool_start",
            step_index,
            tool=response.plan.tool,
            timing_phase="tool_start",
            public_summary=f"正在调用：{response.plan.tool_label}",
        ), event_sink)
        tool_started = time.perf_counter()
        try:
            response = strategy_selector.execute_agent_plan(db, response, limit=limit)
        except Exception:
            logger.exception("ReAct 工具执行失败: tool={}", response.plan.tool)
            observation = {
                "tool": response.plan.tool,
                "status": "failed",
                "summary": "工具执行失败，已停止本轮 ReAct。",
            }
            observations.append(observation)
            _append_event(react_events, _event(
                "tool_observation",
                step_index,
                tool=response.plan.tool,
                tool_ms=int((time.perf_counter() - tool_started) * 1000),
                timing_phase="tool_execution",
                public_summary=observation["summary"],
                observation=observation,
            ), event_sink)
            return _finish_or_fallback(
                db,
                query,
                context,
                limit,
                current_response,
                react_events,
                "工具执行失败",
                event_sink=event_sink,
            )

        tool_ms = int((time.perf_counter() - tool_started) * 1000)
        observation = _observation_from_response(response)
        observations.append(observation)
        response.react_steps = [*react_events]
        current_response = response
        _append_event(react_events, _event(
            "tool_observation",
            step_index,
            tool=response.plan.tool,
            tool_ms=tool_ms,
            timing_phase="tool_execution",
            public_summary=observation["summary"],
            observation=observation,
        ), event_sink)
        _append_event(react_events, _event(
            "tool_done",
            step_index,
            tool=response.plan.tool,
            tool_ms=tool_ms,
            timing_phase="tool_execution",
            public_summary="工具执行完成。",
            observation=observation,
        ), event_sink)
        return _finalize_tool_response(response, react_events, step_index, event_sink=event_sink)

    return _finish_or_fallback(
        db,
        query,
        context,
        limit,
        current_response,
        react_events,
        "ReAct 达到最大步数，已使用当前观察结果结束",
        event_sink=event_sink,
    )


def _execute_prepared_response(
    db: Session,
    response: StrategyAgentResponse,
    limit: int,
    react_events: list[dict[str, Any]],
    *,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> StrategyAgentResponse:
    if response.plan.tool not in EXECUTABLE_TOOLS:
        step_index = len([event for event in react_events if event["type"] == "react_step"]) + 1
        _append_event(react_events, _event(
            "final",
            step_index,
            tool=response.plan.tool,
            timing_phase="local_final",
            fallback_reason=_fallback_from_response(response),
            public_summary="本地确定性响应已生成。",
        ), event_sink)
        response.react_steps = react_events
        return response
    step_index = len([event for event in react_events if event["type"] == "react_step"]) + 1
    _append_event(react_events, _event(
        "tool_start",
        step_index,
        tool=response.plan.tool,
        timing_phase="tool_start",
        public_summary=f"正在调用：{response.plan.tool_label}",
        fallback_reason=_fallback_from_response(response),
    ), event_sink)
    tool_started = time.perf_counter()
    response = strategy_selector.execute_agent_plan(db, response, limit=limit)
    tool_ms = int((time.perf_counter() - tool_started) * 1000)
    observation = _observation_from_response(response)
    _append_event(react_events, _event(
        "tool_observation",
        step_index,
        tool=response.plan.tool,
        tool_ms=tool_ms,
        timing_phase="tool_execution",
        fallback_reason=_fallback_from_response(response),
        public_summary=observation["summary"],
        observation=observation,
    ), event_sink)
    _append_event(react_events, _event(
        "tool_done",
        step_index,
        tool=response.plan.tool,
        tool_ms=tool_ms,
        timing_phase="tool_execution",
        fallback_reason=_fallback_from_response(response),
        public_summary="工具执行完成。",
        observation=observation,
    ), event_sink)
    return _finalize_tool_response(response, react_events, step_index, event_sink=event_sink)


def _response_from_model_plan(
    db: Session,
    query: str,
    context: dict[str, Any],
    model_plan: qwen_client.AgentPlanResult,
    *,
    step_index: int,
) -> StrategyAgentResponse:
    if model_plan.tool == "stock_detail":
        detail_response = strategy_selector.build_stock_detail_response_from_db(
            db,
            query,
            context,
            ai_configured=True,
        )
        if detail_response is None:
            target = strategy_selector._resolve_stock_detail_target_from_db(
                db,
                " ".join([
                    str(model_plan.extra.get("code") or ""),
                    str(model_plan.extra.get("name") or ""),
                ]).strip(),
            )
            detail_response = strategy_selector.build_stock_detail_response(
                query,
                context,
                ai_configured=True,
                code=target["code"] if target else "",
                name=str(target.get("name") or "") if target else "",
            )
        detail_response.plan.ai_used = True
        detail_response.plan.reasoning = model_plan.reasoning
        trace_summary = (
            f"ReAct step {step_index}: 模型选择 stock_detail 并通过校验"
            if detail_response.plan.tool == "stock_detail"
            else f"ReAct step {step_index}: 模型选择 stock_detail，但未定位到有效详情目标"
        )
        detail_response.tool_trace = [
            trace_summary,
            *detail_response.tool_trace[1:],
        ]
        return detail_response

    non_executing = strategy_selector._build_non_executing_model_response(
        query,
        context,
        model_plan,
    )
    if non_executing is not None:
        non_executing.tool_trace = [
            f"ReAct step {step_index}: 模型选择 {model_plan.tool} 并通过校验",
            *non_executing.tool_trace[1:],
        ]
        return non_executing

    plan = StrategyAgentPlan(
        tool=model_plan.tool,
        tool_label=model_plan.tool_label,
        reasoning=model_plan.reasoning,
        conditions=model_plan.conditions,
        condition_labels=strategy_selector._condition_labels(model_plan.conditions),
        logic=model_plan.logic if model_plan.logic in ("AND", "OR") else "AND",
        sort_by=model_plan.sort_by,
        sort_desc=model_plan.sort_desc,
        limit=min(max(model_plan.limit, 1), 200),
        offset=min(max(model_plan.offset, 0), 10_000),
        strategy_id=model_plan.strategy_id,
        ai_configured=True,
        ai_used=True,
    )

    unsupported_metrics = strategy_selector._unsupported_metric_labels(query)
    if plan.tool == "stock_screen" and unsupported_metrics:
        response = strategy_selector.build_unsupported_metric_response(
            query,
            unsupported_metrics,
            ai_configured=True,
        )
        response.plan.ai_used = True
        response.warnings = [
            f"当前数据字段不支持：{'、'.join(unsupported_metrics)}。已停止筛选，避免返回不满足全部条件的股票。",
        ]
        response.tool_trace = [
            f"ReAct step {step_index}: 模型选择 stock_screen，但安全层发现不支持字段",
            *response.tool_trace,
        ]
        return response

    if plan.tool == "stock_screen" and not plan.conditions and not strategy_selector.is_explicit_all_stocks_query(query):
        response = strategy_selector.build_clarification_response(query, ai_configured=True)
        response.plan.ai_used = True
        response.warnings = ["模型未返回有效筛选条件，已阻止无条件全市场筛选。"]
        response.tool_trace = [
            f"ReAct step {step_index}: 模型返回空筛选条件，安全层拦截",
            *response.tool_trace,
        ]
        return response

    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer="工具规划完成，等待执行。",
        tool_trace=[f"ReAct step {step_index}: 模型选择 {plan.tool} 并通过校验"],
        tool_calls=strategy_selector._planned_tool_calls(plan),
    )


def _apply_final_answer(
    query: str,
    current_response: StrategyAgentResponse | None,
    final_answer: str,
    public_reason: str,
    *,
    ai_configured: bool,
) -> StrategyAgentResponse:
    if current_response is not None:
        if final_answer.strip():
            current_response.answer = final_answer.strip()
        current_response.tool_trace = [
            *current_response.tool_trace,
            public_reason or "ReAct final：模型基于工具 observation 生成最终回答",
        ]
        return current_response

    plan = StrategyAgentPlan(
        tool="ask_clarification",
        tool_label="普通回复",
        reasoning=public_reason or "模型未调用工具，直接生成最终回答。",
        ai_configured=ai_configured,
        ai_used=True,
    )
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=final_answer.strip() or "我需要更多条件才能继续。",
        tool_trace=["ReAct final：模型未调用工具，直接回答"],
        tool_calls=[],
    )


def _finalize_tool_response(
    response: StrategyAgentResponse,
    react_events: list[dict[str, Any]],
    step_index: int,
    *,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> StrategyAgentResponse:
    response.tool_trace = [
        *response.tool_trace,
        "ReAct 工具已执行，使用后端确定性总结结束",
    ]
    _append_event(react_events, _event(
        "final",
        step_index,
        tool=response.plan.tool,
        timing_phase="local_final",
        public_summary="工具结果已返回，已使用后端确定性总结。",
        fallback_reason=_fallback_from_response(response),
    ), event_sink)
    response.react_steps = [*react_events]
    return response


def _finish_or_fallback(
    db: Session,
    query: str,
    context: dict[str, Any],
    limit: int,
    current_response: StrategyAgentResponse | None,
    react_events: list[dict[str, Any]],
    reason: str,
    *,
    model_ms: int = 0,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> StrategyAgentResponse:
    if current_response is not None:
        current_response.warnings = [*current_response.warnings, f"最终总结未完成：{reason}"]
        current_response.tool_trace = [*current_response.tool_trace, f"ReAct 工具已执行，最终总结未完成：{reason}"]
        _append_event(react_events, _event(
            "final",
            len([event for event in react_events if event["type"] == "react_step"]) + 1,
            tool=current_response.plan.tool,
            model_ms=model_ms,
            fallback_reason=reason,
            timing_phase="model_final_fallback",
            public_summary=f"模型最终总结未完成，已展示工具结果：{reason}",
        ), event_sink)
        current_response.react_steps = [*react_events]
        return current_response

    response = _non_executing_model_failure_response(
        query,
        reason,
        ai_configured=strategy_selector.is_ai_configured(),
    )
    response.react_steps = react_events
    _append_event(response.react_steps, _event(
        "final",
        1,
        tool=response.plan.tool,
        model_ms=model_ms,
        fallback_reason=reason,
        timing_phase="model_action_stopped",
        public_summary=f"{reason}，未调用选股工具。",
    ), event_sink)
    return response


def _non_executing_model_failure_response(
    query: str,
    reason: str,
    *,
    ai_configured: bool,
) -> StrategyAgentResponse:
    plan = StrategyAgentPlan(
        tool="ask_clarification",
        tool_label="普通回复",
        reasoning="模型没有产生可执行工具调用；后端不自动执行本地筛选。",
        ai_configured=ai_configured,
        ai_used=False,
    )
    answer = "\n".join([
        "我现在没有拿到可靠的工具调用结果，所以不执行筛选。",
        f"原因：{reason}。",
        "你可以稍后重试，或者直接用结构化筛选条件执行。",
    ])
    return StrategyAgentResponse(
        query=query,
        plan=plan,
        answer=answer,
        warnings=[reason],
        tool_trace=[
            "ReAct 未产生可执行工具调用",
            "未调用 screener_engine.screen：没有通过模型 schema 校验的工具 action",
        ],
        tool_calls=[],
    )


def _observation_from_response(response: StrategyAgentResponse) -> dict[str, Any]:
    plan = response.plan
    if response.screen_result is not None:
        result = response.screen_result
        items = [
            {"code": item.code, "name": item.name}
            for item in result.items[:5]
        ]
        return {
            "tool": plan.tool,
            "status": "done",
            "total": result.total,
            "returned": len(result.items),
            "trade_date": result.trade_date,
            "items": items,
            "conditions": [cond.model_dump() for cond in (result.parsed_conditions or plan.conditions)],
            "summary": f"股票筛选完成，命中 {result.total} 只，返回 {len(result.items)} 只。",
        }
    if response.strategy_result is not None:
        result = response.strategy_result
        items = [
            {"code": item.code, "name": item.name}
            for item in result.items[:5]
        ]
        return {
            "tool": plan.tool,
            "status": "done",
            "strategy_id": result.strategy.id,
            "total": result.total,
            "returned": len(result.items),
            "trade_date": result.trade_date,
            "items": items,
            "summary": f"策略选股完成，策略 {result.strategy.id} 命中 {result.total} 只。",
        }
    return {
        "tool": plan.tool,
        "status": "done",
        "summary": response.answer[:240],
    }


def _action_key(plan: qwen_client.AgentPlanResult) -> str:
    payload = {
        "tool": plan.tool,
        "conditions": [cond.model_dump() for cond in plan.conditions],
        "logic": plan.logic,
        "sort_by": plan.sort_by,
        "sort_desc": plan.sort_desc,
        "limit": plan.limit,
        "offset": plan.offset,
        "strategy_id": plan.strategy_id,
        "extra": plan.extra,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _fallback_from_response(response: StrategyAgentResponse) -> str | None:
    if response.plan.ai_used:
        return None
    if response.tool_trace and response.tool_trace[0].startswith("本地快速路径命中"):
        return "local_fast_path"
    if response.warnings:
        return response.warnings[0]
    if response.plan.ai_configured:
        return "local_rules"
    return None


def _append_event(
    react_events: list[dict[str, Any]],
    payload: dict[str, Any],
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    react_events.append(payload)
    if event_sink is not None:
        event_sink(payload)


def _event(
    event_type: str,
    step_index: int,
    *,
    tool: str | None = None,
    model_ms: int = 0,
    tool_ms: int = 0,
    fallback_reason: str | None = None,
    timing_phase: str = "",
    public_summary: str = "",
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "type": event_type,
        "step_index": step_index,
        "tool": tool,
        "model_ms": int(model_ms or 0),
        "tool_ms": int(tool_ms or 0),
        "fallback_reason": fallback_reason,
        "timing_phase": timing_phase,
        "public_summary": public_summary,
    }
    if observation is not None:
        payload["observation"] = observation
    return payload
