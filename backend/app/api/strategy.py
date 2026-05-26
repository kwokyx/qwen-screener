from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.backtest import BacktestRequest, BacktestResponse
from app.services import backtest_engine


router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(req: BacktestRequest, db: Session = Depends(get_db)):
    """运行策略回测，返回净值曲线 / 关键指标 / 交易日志。"""
    try:
        return backtest_engine.run_backtest(db, req)
    except ValueError as e:
        raise HTTPException(400, str(e))
