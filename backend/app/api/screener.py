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

    def gen():
        yield event({"type": "thinking", "text": "正在判断需求类型与可用工具…\n"})
        try:
            response = strategy_selector.run_chat_agent(
                db,
                req.query,
                context=req.context or {},
                limit=50,
            )
        except Exception as e:
            logger.exception("Agent 智能筛选失败")
            yield event({"type": "error", "message": f"智能筛选失败: {e}"})
            return

        plan = response.plan
        common = {
            "plan": plan.model_dump(),
            "conditions": [c.model_dump() for c in plan.conditions],
            "answer": response.answer,
            "warnings": response.warnings,
            "tool_trace": response.tool_trace,
        }

        if plan.tool == "stock_screen":
            yield event({
                "type": "parsed",
                **common,
                "logic": plan.logic,
                "sort_by": plan.sort_by,
                "sort_desc": plan.sort_desc,
                "limit": 50,
            })
            yield event({"type": "screening"})
            if response.screen_result is None:
                yield event({"type": "error", "message": "筛选工具没有返回结果"})
                return
            yield event({
                "type": "result",
                **common,
                **screen_result_payload(response.screen_result),
            })
            yield event({"type": "done"})
            return

        if plan.tool == "strategy_design":
            yield event({"type": "design", **common})
            yield event({"type": "done"})
            return

        payload = {"type": "agent", **common}
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
