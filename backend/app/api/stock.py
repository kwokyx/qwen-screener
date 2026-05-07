from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.models.user import User
from app.models.watchlist import Watchlist
from app.schemas.stock import (
    StockBasicOut,
    StockDailyOut,
    StockDetailOut,
    WatchlistCreate,
    WatchlistOut,
)


router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/search", response_model=list[StockBasicOut])
def search(q: str = Query(min_length=1), limit: int = 20, db: Session = Depends(get_db)):
    """按代码或名称模糊搜索"""
    pattern = f"%{q}%"
    return (
        db.query(StockBasic)
        .filter((StockBasic.code.like(pattern)) | (StockBasic.name.like(pattern)))
        .limit(limit)
        .all()
    )


@router.get("/{code}", response_model=StockDetailOut)
def detail(code: str, db: Session = Depends(get_db)):
    basic = db.get(StockBasic, code)
    if not basic:
        raise HTTPException(404, "股票不存在")
    last2 = (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(2)
        .all()
    )
    latest_daily = last2[0] if last2 else None
    prev_close = last2[1].close if len(last2) > 1 else None
    change_pct = None
    if latest_daily and prev_close and latest_daily.close is not None:
        change_pct = (latest_daily.close - prev_close) / prev_close * 100

    latest_fin = (
        db.query(StockFinancial)
        .filter(StockFinancial.code == code)
        .order_by(desc(StockFinancial.report_date))
        .first()
    )
    return StockDetailOut(
        code=basic.code,
        name=basic.name,
        industry=basic.industry,
        latest=StockDailyOut.model_validate(latest_daily) if latest_daily else None,
        prev_close=prev_close,
        change_pct=change_pct,
        roe=latest_fin.roe if latest_fin else None,
        revenue_yoy=latest_fin.revenue_yoy if latest_fin else None,
        profit_yoy=latest_fin.profit_yoy if latest_fin else None,
        gross_margin=latest_fin.gross_margin if latest_fin else None,
        debt_ratio=latest_fin.debt_ratio if latest_fin else None,
    )


@router.get("/{code}/kline", response_model=list[StockDailyOut])
def kline(code: str, days: int = 120, db: Session = Depends(get_db)):
    return (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(days)
        .all()
    )


# ----- 自选股 -----

@router.get("/me/watchlist", response_model=list[WatchlistOut])
def list_watch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Watchlist).filter(Watchlist.user_id == user.id).all()


@router.post("/me/watchlist", response_model=WatchlistOut, status_code=201)
def add_watch(
    payload: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db.get(StockBasic, payload.code):
        raise HTTPException(404, "股票不存在")
    exists = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == user.id, Watchlist.code == payload.code)
        .first()
    )
    if exists:
        return exists
    item = Watchlist(user_id=user.id, code=payload.code, note=payload.note)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/me/watchlist/{code}", status_code=204)
def remove_watch(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Watchlist).filter(
        Watchlist.user_id == user.id, Watchlist.code == code
    ).delete()
    db.commit()
