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
    """返回最近 N 个交易日 OHLCV。本地行数不够时，
    先去 akshare 拉一次历史回填，避免 sparkline / 详情页 K 线画不出来。
    """
    have = db.query(StockDaily).filter(StockDaily.code == code).count()
    if have < days:
        _backfill_kline(db, code, days)
    return (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(days)
        .all()
    )


def _backfill_kline(db: Session, code: str, days: int) -> int:
    """从 akshare 拉 daily hist 写入 stock_daily。已有日期 skip。"""
    from datetime import date, timedelta
    import akshare as ak

    sym = code.split(".")[0]
    end = date.today()
    # 多拉 60 天缓冲（节假日、停牌）
    start = end - timedelta(days=max(days * 2, 60))
    try:
        df = ak.stock_zh_a_hist(
            symbol=sym, period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
    except Exception:
        return 0
    if df is None or df.empty:
        return 0

    have_dates = {r[0] for r in db.query(StockDaily.trade_date).filter(StockDaily.code == code).all()}
    inserted = 0
    for _, r in df.iterrows():
        raw = r.get("日期")
        if isinstance(raw, date):
            td = raw
        else:
            try:
                td = date.fromisoformat(str(raw))
            except Exception:
                continue
        if td in have_dates:
            continue
        try:
            db.add(StockDaily(
                code=code, trade_date=td,
                open=float(r.get("开盘") or 0) or None,
                high=float(r.get("最高") or 0) or None,
                low=float(r.get("最低") or 0) or None,
                close=float(r.get("收盘") or 0) or None,
                volume=float(r.get("成交量") or 0) or None,
                amount=float(r.get("成交额") or 0) or None,
                turnover=float(r.get("换手率") or 0) or None,
            ))
            inserted += 1
        except Exception:
            db.rollback()
            continue
    if inserted:
        db.commit()
    return inserted


# ----- 自选股 -----

@router.get("/me/watchlist", response_model=list[WatchlistOut])
def list_watch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Watchlist).filter(Watchlist.user_id == user.id).all()


@router.post("/me/watchlist", response_model=WatchlistOut)
def add_watch(
    payload: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """upsert：已存在则更新 alerts / note / ref_price，不存在则插入。
    前端 store 在每次本地变更（加股 / 改预警）后都会 POST 上来。
    """
    if not db.get(StockBasic, payload.code):
        raise HTTPException(404, "股票不存在")
    item = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == user.id, Watchlist.code == payload.code)
        .first()
    )
    if item is None:
        item = Watchlist(user_id=user.id, code=payload.code)
        db.add(item)
    if payload.note is not None:
        item.note = payload.note
    if payload.alerts is not None:
        item.alerts = payload.alerts
    if payload.ref_price is not None:
        item.ref_price = payload.ref_price
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
