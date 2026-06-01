import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.screener import NLScreenRequest, ScreenRequest, ScreenResponse
from app.services import qwen_client, screener_engine, strategy_selector


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
    """自然语言筛选：千问解析 → 引擎执行（一次性返回）"""
    try:
        parsed = qwen_client.parse_nl_query(req.query)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if not parsed.conditions and not strategy_selector.is_explicit_all_stocks_query(req.query):
        raise HTTPException(400, "未识别到可执行筛选条件，请补充指标或明确要求查看全部股票")
    try:
        result = screener_engine.screen(db, parsed)
    except ValueError as e:
        raise HTTPException(400, f"千问解析的条件无效: {e}")
    result.parsed_conditions = parsed.conditions
    return result


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

    def response_payload(response) -> dict:
        plan = response.plan
        return {
            "plan": plan.model_dump(),
            "conditions": [c.model_dump() for c in plan.conditions],
            "answer": response.answer,
            "warnings": response.warnings,
            "tool_trace": response.tool_trace,
            "tool_calls": [call.model_dump() for call in response.tool_calls],
        }

    def _stage_text(tool: str, source: str) -> str:
        """Return truthful SSE stage text for each tool."""
        labels = {
            "stock_screen": "正在执行筛选",
            "strategy_design": "正在生成策略",
            "strategy_select": "正在执行策略选股",
            "explain_result": "正在解释结果",
            "ask_clarification": "正在请求补充信息",
        }
        return f"{labels.get(tool, '正在处理')}（{source}）…\n"

    def gen():
        yield event({"type": "thinking", "text": "正在判断需求…\n"})
        try:
            response = strategy_selector.plan_chat_agent(
                req.query,
                context=req.context or {},
                limit=50,
            )
        except Exception as e:
            logger.exception("Agent 规划失败")
            yield event({"type": "error", "message": f"智能筛选规划失败: {e}"})
            return

        plan = response.plan
        source = "AI 模型" if plan.ai_used else "本地规则"
        effective_limit = min(max(plan.limit, 1), 50)
        logger.info(
            "Agent SSE 规划完成: tool={} source={} validated=true conditions={}",
            plan.tool,
            "model" if plan.ai_used else "local",
            len(plan.conditions),
        )
        yield event({"type": "thinking", "text": f"已选择工具：{plan.tool_label}（{source}）\n"})
        yield event({"type": "thinking", "text": "参数校验已完成\n"})

        common = response_payload(response)
        for call in response.tool_calls:
            yield event({"type": "tool_call", "tool_call": call.model_dump()})

        if plan.tool == "stock_screen":
            logger.info(
                "Agent SSE 执行工具: tool=stock_screen conditions={} limit={}",
                len(plan.conditions),
                effective_limit,
            )
            yield event({
                "type": "parsed",
                **common,
                "logic": plan.logic,
                "sort_by": plan.sort_by,
                "sort_desc": plan.sort_desc,
                "limit": effective_limit,
                "offset": plan.offset,
            })
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source)})
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
            try:
                response = strategy_selector.execute_agent_plan(db, response, limit=effective_limit)
            except Exception as e:
                logger.exception("结构化股票筛选失败")
                yield event({"type": "error", "message": f"筛选工具执行失败: {e}"})
                return
            if response.screen_result is None:
                yield event({"type": "error", "message": "筛选工具没有返回结果"})
                return
            logger.info(
                "Agent SSE 工具完成: tool=stock_screen total={}",
                response.screen_result.total,
            )
            yield event({
                "type": "result",
                **response_payload(response),
                **screen_result_payload(response.screen_result),
            })
            yield event({"type": "thinking", "text": "已生成结果\n"})
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_design":
            logger.info("Agent SSE 跳过执行: tool=strategy_design reason=non-executing")
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source)})
            yield event({"type": "design", **common})
            yield event({"type": "thinking", "text": "已生成策略设计方案\n"})
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_select":
            logger.info(
                "Agent SSE 执行工具: tool=strategy_select strategy_id={} limit={}",
                plan.strategy_id,
                effective_limit,
            )
            yield event({"type": "planned", **common})
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source)})
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
            try:
                response = strategy_selector.execute_agent_plan(db, response, limit=effective_limit)
            except Exception as e:
                logger.exception("策略选股失败")
                yield event({"type": "error", "message": f"策略选股执行失败: {e}"})
                return
            logger.info(
                "Agent SSE 工具完成: tool=strategy_select total={}",
                response.strategy_result.total if response.strategy_result else 0,
            )

        # explain_result / ask_clarification are non-executing
        if plan.tool in ("explain_result", "ask_clarification"):
            logger.info("Agent SSE 跳过执行: tool={} reason=non-executing", plan.tool)
            yield event({"type": "thinking", "text": _stage_text(plan.tool, source)})

        payload = {"type": "agent", **response_payload(response)}
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
