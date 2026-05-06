from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.services import qwen_client


router = APIRouter(prefix="/qwen", tags=["qwen"])


@router.get("/analysis/{code}")
def analyze(code: str, db: Session = Depends(get_db)):
    """让千问基于该股票最新基本面数据生成投资分析"""
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
    snapshot = {
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
        "dividend_yield": fin.dividend_yield if fin else None,
    }
    try:
        text = qwen_client.analyze_stock(snapshot)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"code": code, "analysis": text, "snapshot": snapshot}
