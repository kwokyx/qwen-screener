import json
from queue import Queue
from threading import Thread
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.schemas.screener import NLScreenRequest, ScreenRequest, ScreenResponse
from app.services import agent_react, screener_engine, strategy_selector


router = APIRouter(prefix="/screener", tags=["screener"])


@router.post("", response_model=ScreenResponse)
def run_screen(req: ScreenRequest, db: Session = Depends(get_db)):
    """传统多条件筛选"""
    try:
        return screener_engine.screen(db, req)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/nl", response_model=ScreenResponse)
def run_nl_screen(req: NLScreenRequest, db: Session = Depends(get_db)):
    """自然语言筛选：bounded ReAct 选择筛选工具后一次性返回结果。"""
    try:
        response = agent_react.run_chat_react_agent(
            db,
            req.query,
            context=req.context or {},
            limit=50,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if response.screen_result is None:
        raise HTTPException(400, response.answer)
    return response.screen_result


@router.post("/nl/stream")
def run_nl_screen_stream(req: NLScreenRequest, db: Session = Depends(get_db)):
    """自然语言智能筛选（流式 SSE）。"""

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n".encode("utf-8")

    def screen_result_payload(result) -> dict:
        return {
            "total": result.total,
            "items": [it.model_dump() for it in result.items],
            "offset": result.offset,
            "limit": result.limit,
            "trade_date": result.trade_date,
            "parsed_conditions": [c.model_dump() for c in (result.parsed_conditions or [])],
        }

    def strategy_result_payload(result) -> dict:
        return {
            "total": result.total,
            "items": [it.model_dump() for it in result.items],
            "parsed_conditions": [],
            "strategy": result.strategy.model_dump(),
            "trade_date": result.trade_date,
        }

    def is_no_tool_agent_response(response) -> bool:
        return (
            response.plan.tool == "ask_clarification"
            and response.screen_result is None
            and response.strategy_result is None
        )

    def is_deferred_no_tool_step(payload: dict) -> bool:
        return (
            payload.get("tool") == "ask_clarification"
            and payload.get("type") in {"react_step", "final"}
        )

    def response_payload(response, timings: dict | None = None) -> dict:
        timings = timings or {}
        plan = response.plan
        timing_payload = {
            "planning_ms": int(timings.get("planning_ms") or 0),
            "model_ms": int(timings.get("model_ms") or 0),
            "tool_ms": int(timings.get("tool_ms") or 0),
            "fallback_reason": timings.get("fallback_reason"),
            "completion_reason": timings.get("completion_reason"),
        }
        non_executing_model_stop = (
            plan.tool == "ask_clarification"
            and plan.ai_configured
            and not plan.ai_used
            and timing_payload["fallback_reason"] not in (None, "local_fast_path", "local_rules")
        )
        if plan.ai_used:
            ai_source = "ai_agent"
            ai_label = "AI Agent"
            ai_fallback = False
        elif non_executing_model_stop:
            ai_source = "chat_only"
            ai_label = "普通回复"
            ai_fallback = False
        elif timing_payload["fallback_reason"] == "local_fast_path":
            ai_source = "local_deterministic" if plan.ai_configured else "local_rules"
            ai_label = "本地处理" if plan.ai_configured else "本地规则"
            ai_fallback = False
        else:
            ai_source = "local_fallback" if plan.ai_configured else "local_rules"
            ai_label = "本地处理" if plan.ai_configured else "本地规则"
            ai_fallback = plan.ai_configured and not plan.ai_used
        return {
            "query": response.query,
            "plan": plan.model_dump(),
            "conditions": [c.model_dump() for c in plan.conditions],
            "answer": response.answer,
            "warnings": response.warnings,
            "tool_trace": response.tool_trace,
            "tool_calls": [] if is_no_tool_agent_response(response) else [call.model_dump() for call in response.tool_calls],
            "react_steps": response.react_steps,
            "timings": timing_payload,
            "planning_ms": timing_payload["planning_ms"],
            "model_ms": timing_payload["model_ms"],
            "tool_ms": timing_payload["tool_ms"],
            "fallback_reason": timing_payload["fallback_reason"],
            "completion_reason": timing_payload["completion_reason"],
            "ai_status": {
                "configured": plan.ai_configured,
                "used": plan.ai_used,
                "source": ai_source,
                "label": ai_label,
                "fallback": ai_fallback,
            },
        }

    def _stage_text(tool: str, source: str, tool_label: str | None = None) -> str:
        """Return truthful SSE stage text for each tool."""
        labels = {
            "stock_screen": "股票筛选",
            "strategy_design": "策略设计",
            "strategy_select": "策略选股",
            "explain_result": "结果解释",
            "sort_results": "结果排序",
            "paginate_results": "结果分页",
            "stock_detail": "详情页定位",
            "ask_clarification": "补充追问",
        }
        label = labels.get(tool, "处理")
        if tool in {"ask_clarification", "strategy_design", "explain_result", "stock_detail"} and tool_label:
            label = tool_label
        if tool in {"stock_screen", "strategy_select"}:
            return f"正在执行本地工具：{label}…\n"
        if tool in {"sort_results", "paginate_results"}:
            return f"正在执行本地结果操作：{label}…\n"
        return f"正在整理响应：{label}（{source}）…\n"

    def _fallback_reason(response) -> str | None:
        plan = response.plan
        if plan.ai_used:
            return None
        if response.tool_trace and response.tool_trace[0].startswith("本地快速路径命中"):
            return "local_fast_path"
        if response.warnings:
            return response.warnings[0]
        if plan.ai_configured:
            return "local_rules"
        return None

    def _react_timings(response) -> dict:
        steps = response.react_steps or []
        model_ms = sum(int(step.get("model_ms") or 0) for step in steps)
        tool_ms = sum(
            int(step.get("tool_ms") or 0)
            for step in steps
            if step.get("type") == "tool_done"
        )
        model_fallback_reason = next(
            (
                step.get("fallback_reason")
                for step in reversed(steps)
                if step.get("type") == "final"
                and step.get("fallback_reason")
                and step.get("timing_phase") == "model_action_stopped"
            ),
            None,
        )
        completion_reason = next(
            (
                step.get("fallback_reason")
                for step in reversed(steps)
                if step.get("type") == "final"
                and step.get("fallback_reason")
                and step.get("timing_phase") == "model_final_fallback"
            ),
            None,
        )
        fallback_reason = model_fallback_reason or next(
            (
                step.get("fallback_reason")
                for step in steps
                if step.get("fallback_reason")
                and step.get("timing_phase") != "model_final_fallback"
            ),
            _fallback_reason(response),
        )
        return {
            "planning_ms": model_ms,
            "model_ms": model_ms,
            "tool_ms": tool_ms,
            "fallback_reason": fallback_reason,
            "completion_reason": completion_reason,
        }

    def gen():
        planning_started = time.perf_counter()
        stream_queue = Queue()
        deferred_steps: list[dict] = []

        def push_step(payload: dict):
            stream_queue.put(("step", payload))

        def run_agent_worker():
            try:
                with SessionLocal() as worker_db:
                    response = agent_react.run_chat_react_agent(
                        worker_db,
                        req.query,
                        context=req.context or {},
                        limit=50,
                        event_sink=push_step,
                    )
                stream_queue.put(("response", response))
            except Exception as exc:
                logger.exception("Agent 规划失败")
                stream_queue.put(("error", exc))

        Thread(target=run_agent_worker, daemon=True).start()

        response = None
        while response is None:
            kind, payload = stream_queue.get()
            if kind == "step":
                if is_deferred_no_tool_step(payload):
                    deferred_steps.append(payload)
                else:
                    yield event(payload)
            elif kind == "response":
                response = payload
            elif kind == "error":
                yield event({"type": "error", "message": f"智能筛选规划失败: {payload}"})
                return

        timings = _react_timings(response)
        wall_ms = int((time.perf_counter() - planning_started) * 1000)
        timings["planning_ms"] = max(int(timings.get("planning_ms") or 0), wall_ms)
        plan = response.plan
        source = (
            "AI 模型"
            if plan.ai_used
            else (
                "普通回复"
                if plan.tool == "ask_clarification"
                and timings.get("fallback_reason") not in (None, "local_fast_path", "local_rules")
                else ("本地处理" if plan.ai_configured else "本地规则")
            )
        )
        effective_limit = min(max(plan.limit, 1), 50)
        logger.info(
            "Agent SSE ReAct 完成: tool={} source={} validated=true conditions={} planning_ms={} model_ms={} tool_ms={} fallback_reason={}",
            plan.tool,
            "model" if plan.ai_used else "local",
            len(plan.conditions),
            timings["planning_ms"],
            timings["model_ms"],
            timings["tool_ms"],
            timings["fallback_reason"],
        )

        common = response_payload(response, timings)
        if is_no_tool_agent_response(response):
            yield event({"type": "agent", **common})
            yield event({"type": "done"})
            return

        for step in deferred_steps:
            yield event(step)

        yield event({"type": "thinking", "text": f"已选择工具：{plan.tool_label}（{source}，模型耗时 {timings['model_ms']}ms）\n"})
        yield event({"type": "thinking", "text": "参数校验已完成\n"})

        pre_tool_timings = {**timings, "tool_ms": 0}
        pre_tool_common = response_payload(response, pre_tool_timings)
        yield event({"type": "planning", **common})
        for call in response.tool_calls:
            yield event({"type": "tool_call", "tool_call": call.model_dump()})

        if response.screen_result is not None:
            is_result_operation = plan.tool in {"sort_results", "paginate_results"}
            logger.info(
                "Agent SSE 返回结果: tool={} conditions={} limit={} total={}",
                plan.tool,
                len(plan.conditions),
                effective_limit,
                response.screen_result.total,
            )
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source, plan.tool_label)})
            if not is_result_operation:
                yield event({
                    "type": "parsed",
                    **pre_tool_common,
                    "logic": plan.logic,
                    "sort_by": plan.sort_by,
                    "sort_desc": plan.sort_desc,
                    "limit": effective_limit,
                    "offset": plan.offset,
                })
                yield event({
                    "type": "screening",
                    "tool": plan.tool,
                    "tool_label": plan.tool_label,
                    "tool_call": {
                        "id": "stock_screen",
                        "name": "stock_screen",
                        "label": plan.tool_label,
                        "status": "running",
                        "params": {
                            "conditions": len(plan.conditions),
                            "sort_by": plan.sort_by,
                            "offset": plan.offset,
                            "limit": effective_limit,
                        },
                        "result": {},
                        "message": "正在调用本地筛选引擎",
                    },
                })
            yield event({
                "type": "result",
                **response_payload(response, timings),
                **screen_result_payload(response.screen_result),
            })
            yield event({"type": "thinking", "text": "已生成结果\n"})
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_design":
            logger.info("Agent SSE 跳过执行: tool=strategy_design reason=non-executing")
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source, plan.tool_label)})
            yield event({"type": "design", **common})
            yield event({"type": "thinking", "text": "已生成策略设计方案\n"})
            yield event({"type": "done"})
            return

        if response.strategy_result is not None:
            logger.info(
                "Agent SSE 返回策略结果: tool=strategy_select strategy_id={} limit={} total={}",
                plan.strategy_id,
                effective_limit,
                response.strategy_result.total,
            )
            yield event({"type": "planned", **pre_tool_common})
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source, plan.tool_label)})
            yield event({
                "type": "screening",
                "tool": plan.tool,
                "tool_label": plan.tool_label,
                "tool_call": {
                    "id": "strategy_select",
                    "name": "strategy_select",
                    "label": plan.tool_label,
                    "status": "running",
                    "params": {"strategy_id": plan.strategy_id, "limit": effective_limit},
                    "result": {},
                    "message": "正在执行策略选股",
                },
            })

        # explain_result / stock_detail / ask_clarification are non-executing
        if plan.tool in ("explain_result", "stock_detail", "ask_clarification"):
            logger.info("Agent SSE 跳过执行: tool={} reason=non-executing", plan.tool)
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source, plan.tool_label)})

        payload = {"type": "agent", **response_payload(response, timings)}
        if response.strategy_result is not None:
            payload["result"] = strategy_result_payload(response.strategy_result)
        yield event(payload)
        yield event({"type": "thinking", "text": "已生成结果\n"})
        yield event({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
