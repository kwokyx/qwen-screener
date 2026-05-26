import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.schemas.qwen_score import StockScoreResponse
from app.services import qwen_client


router = APIRouter(prefix="/qwen", tags=["qwen"])


def _build_snapshot(db: Session, code: str) -> dict:
    """组装个股快照，供两个 analyze 路由共用。"""
    basic = db.get(StockBasic, code)
    if not basic:
        raise HTTPException(404, "股票不存在")
    daily = (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .first()
    )
    fin = (
        db.query(StockFinancial)
        .filter(StockFinancial.code == code)
        .order_by(desc(StockFinancial.report_date))
        .first()
    )
    return {
        "code": basic.code,
        "name": basic.name,
        "industry": basic.industry,
        "pe": daily.pe if daily else None,
        "pb": daily.pb if daily else None,
        "market_cap": daily.market_cap if daily else None,
        "roe": fin.roe if fin else None,
        "revenue_yoy": fin.revenue_yoy if fin else None,
        "profit_yoy": fin.profit_yoy if fin else None,
        "gross_margin": fin.gross_margin if fin else None,
        "debt_ratio": fin.debt_ratio if fin else None,
        "dividend_yield": daily.dividend_yield if daily else None,
    }


@router.get("/score/{code}", response_model=StockScoreResponse)
def score_stock(
    code: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    """基本面评分：数字由规则引擎计算；千问仅生成 ≤40 字解读（可缓存）。"""
    snapshot = _build_snapshot(db, code)
    data = qwen_client.score_stock(snapshot, force_refresh=refresh)
    return StockScoreResponse(**data)


@router.get("/analysis/{code}")
def analyze(code: str, db: Session = Depends(get_db)):
    """让千问基于该股票最新基本面数据生成投资分析（一次性返回）"""
    snapshot = _build_snapshot(db, code)
    try:
        text = qwen_client.analyze_stock(snapshot)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"code": code, "analysis": text, "snapshot": snapshot}


@router.get("/analysis/{code}/stream")
def analyze_stream(code: str, db: Session = Depends(get_db)):
    """流式版本：Server-Sent Events，逐 token 推送。

    协议：
        data: {"type":"meta","snapshot":{...}}\\n\\n
        data: {"type":"chunk","text":"投资亮点"}\\n\\n
        data: {"type":"chunk","text":"…"}\\n\\n
        data: {"type":"done"}\\n\\n

    出错则发：
        data: {"type":"error","message":"..."}\\n\\n
    """
    snapshot = _build_snapshot(db, code)

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    def gen():
        # 先把快照发给前端，便于 UI 立刻渲染上下文
        yield event({"type": "meta", "code": code, "snapshot": snapshot})
        try:
            for chunk in qwen_client.stream_analyze_stock(snapshot):
                yield event({"type": "chunk", "text": chunk})
            yield event({"type": "done"})
        except Exception as e:
            yield event({"type": "error", "message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx 不要缓冲
            "Connection": "keep-alive",
        },
    )
