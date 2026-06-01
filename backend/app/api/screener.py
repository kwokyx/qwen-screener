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
    """自然语言筛选（流式 SSE）。

    前端可以即时看到三个阶段：
        1. thinking — 千问正在生成 JSON，token 实时回流（用作"思考预览"）
        2. parsed   — JSON 完整解析成功，返回结构化条件
        3. result   — 引擎执行完毕，返回命中股票

    协议：data: <json>\\n\\n，payload.type ∈
        'thinking' {text}
        'parsed'   {conditions, sort_by, sort_desc, limit, logic}
        'screening'
        'result'   {total, items, parsed_conditions}
        'error'    {message}
        'done'
    """
    from app.services.qwen_client import _load_prompt, _extract_json, stream_call
    from app.schemas.screener import ScreenRequest

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n".encode("utf-8")

    def gen():
        # ---- 工具路由：策略设计请求不应无脑执行股票筛选 ----
        if strategy_selector.is_strategy_design_query(req.query):
            response = strategy_selector.build_strategy_design_response(
                req.query,
                ai_configured=strategy_selector.is_ai_configured(),
            )
            plan = response.plan
            yield event({"type": "thinking", "text": "tool_router -> strategy_design；不调用 screen_stocks。\n"})
            yield event({
                "type": "design",
                "plan": plan.model_dump(),
                "conditions": [c.model_dump() for c in plan.conditions],
                "answer": response.answer,
                "tool_trace": response.tool_trace,
            })
            yield event({"type": "done"})
            return

        # ---- 阶段 1：流式生成 JSON ----
        prompt = _load_prompt("nl_to_filter.md").replace("{user_query}", req.query)
        buf = []
        try:
            for chunk in stream_call(prompt):
                buf.append(chunk)
                yield event({"type": "thinking", "text": chunk})
        except Exception as e:
            logger.exception("NL 流式解析失败")
            yield event({"type": "error", "message": f"千问调用失败: {e}"})
            return

        # ---- 阶段 2：解析为结构化条件 ----
        raw = "".join(buf)
        try:
            data = _extract_json(raw)
            parsed = ScreenRequest(**data)
        except Exception as e:
            yield event({"type": "error", "message": f"千问输出无法解析为筛选条件: {e}"})
            return
        yield event({
            "type": "parsed",
            "conditions": [c.model_dump() for c in parsed.conditions],
            "logic": parsed.logic,
            "sort_by": parsed.sort_by,
            "sort_desc": parsed.sort_desc,
            "limit": parsed.limit,
        })

        # ---- 阶段 3：执行筛选 ----
        yield event({"type": "screening"})
        try:
            result = screener_engine.screen(db, parsed)
        except ValueError as e:
            yield event({"type": "error", "message": f"千问条件无效: {e}"})
            return
        result.parsed_conditions = parsed.conditions
        yield event({
            "type": "result",
            "total": result.total,
            "items": [it.model_dump() for it in result.items],
            "parsed_conditions": [c.model_dump() for c in (result.parsed_conditions or [])],
        })
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
