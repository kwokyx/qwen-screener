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
        }

    def gen():
        yield event({"type": "thinking", "text": "正在判断需求类型与可用工具…\n"})
        try:
            preview = strategy_selector.preview_chat_plan(
                req.query,
                context=req.context or {},
                limit=50,
            )
            yield event({"type": "thinking", "text": f"已选择「{preview.tool_label}」，正在准备参数…\n"})
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
        common = response_payload(response)

        if plan.tool == "stock_screen":
            yield event({
                "type": "parsed",
                **common,
                "logic": plan.logic,
                "sort_by": plan.sort_by,
                "sort_desc": plan.sort_desc,
                "limit": 50,
            })
            yield event({"type": "screening", "tool": plan.tool, "tool_label": plan.tool_label})
            try:
                response = strategy_selector.execute_agent_plan(db, response, limit=50)
            except Exception as e:
                logger.exception("结构化股票筛选失败")
                yield event({"type": "error", "message": f"筛选工具执行失败: {e}"})
                return
            if response.screen_result is None:
                yield event({"type": "error", "message": "筛选工具没有返回结果"})
                return
            yield event({
                "type": "result",
                **response_payload(response),
                **screen_result_payload(response.screen_result),
            })
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_design":
            yield event({"type": "design", **common})
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_select":
            yield event({"type": "planned", **common})
            yield event({"type": "screening", "tool": plan.tool, "tool_label": plan.tool_label})
            try:
                response = strategy_selector.execute_agent_plan(db, response, limit=50)
            except Exception as e:
                logger.exception("策略选股失败")
                yield event({"type": "error", "message": f"策略选股执行失败: {e}"})
                return

        payload = {"type": "agent", **response_payload(response)}
        if response.strategy_result is not None:
            payload["result"] = strategy_result_payload(response.strategy_result)
        yield event(payload)
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
