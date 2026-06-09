from datetime import date, timedelta
from multiprocessing import Process, Queue
import os
from threading import Lock, Thread
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import SessionLocal, get_db
from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.models.user import User
from app.models.watchlist import Watchlist
from app.schemas.stock import (
    StockBasicOut,
    StockDailyOut,
    StockDetailOut,
    StockIntradayOut,
    StockQuoteOut,
    WatchlistCreate,
    WatchlistOut,
)


router = APIRouter(prefix="/stock", tags=["stock"])

_baostock_intraday_disabled_until = 0.0
_intraday_cache: dict[tuple[str, str, int], tuple[float, list[dict]]] = {}
_INTRADAY_CACHE_TTL = 300
_INTRADAY_FETCH_TIMEOUT = float(os.getenv("BAOSTOCK_INTRADAY_TIMEOUT", "6"))
_INTRADAY_BREAKER_SECONDS = int(os.getenv("BAOSTOCK_INTRADAY_BREAKER_SECONDS", "300"))
_daily_backfill_lock = Lock()
_pending_daily_backfills: set[str] = set()


def _baostock_intraday_available() -> bool:
    return time.monotonic() >= _baostock_intraday_disabled_until


def _disable_baostock_intraday(seconds: int = _INTRADAY_BREAKER_SECONDS):
    global _baostock_intraday_disabled_until
    _baostock_intraday_disabled_until = time.monotonic() + seconds


def _run_daily_backfill(code: str, days: int, provider: str):
    try:
        from app.services.data_sync import backfill_kline_single, backfill_kline_single_bs

        with SessionLocal() as db:
            if provider == "baostock":
                backfill_kline_single_bs(db, code, days)
            else:
                backfill_kline_single(db, code, days)
    except Exception as exc:
        logger.warning("后台补充日 K 失败 {}: {}", code, exc)
    finally:
        with _daily_backfill_lock:
            _pending_daily_backfills.discard(code)


def _queue_daily_backfill(code: str, days: int, provider: str):
    with _daily_backfill_lock:
        if code in _pending_daily_backfills:
            return
        _pending_daily_backfills.add(code)
    Thread(target=_run_daily_backfill, args=(code, days, provider), daemon=True).start()


def _get_intraday_cache(code: str, frequency: str, days: int) -> list[dict] | None:
    item = _intraday_cache.get((code, frequency, days))
    if not item:
        return None
    expires_at, rows = item
    if time.monotonic() >= expires_at:
        _intraday_cache.pop((code, frequency, days), None)
        return None
    return rows


def _set_intraday_cache(code: str, frequency: str, days: int, rows: list[dict]):
    _intraday_cache[(code, frequency, days)] = (time.monotonic() + _INTRADAY_CACHE_TTL, rows)


def _is_weekday_row(row: StockDaily) -> bool:
    return bool(row.trade_date and row.trade_date.weekday() < 5)


def _kline_start_date(days: int, frequency: str) -> str:
    """Convert requested bar count into a conservative calendar start date."""
    today = date.today()
    if frequency == "w":
        delta = days * 8 + 30
    elif frequency == "m":
        delta = days * 32 + 60
    else:
        delta = days * 2 + 30
    return (today - timedelta(days=delta)).strftime("%Y-%m-%d")


def _stock_daily_out(row: dict | StockDaily) -> dict:
    if isinstance(row, dict):
        return {
            "code": row.get("code"),
            "trade_date": row.get("trade_date"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
            "pe": row.get("pe"),
            "pb": row.get("pb"),
            "market_cap": row.get("market_cap"),
            "dividend_yield": row.get("dividend_yield"),
            "turnover": row.get("turnover"),
        }
    return StockDailyOut.model_validate(row).model_dump()


def _fetch_intraday_worker(queue: Queue, code: str, start_date: str, end_date: str, frequency: str):
    try:
        from app.services.providers.baostock_provider import fetch_intraday_kline

        rows = fetch_intraday_kline(
            code,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
        )
        queue.put(("ok", rows))
    except Exception as exc:
        queue.put(("error", str(exc)))


def _fetch_intraday_with_timeout(code: str, start_date: str, end_date: str, frequency: str, timeout: float = 25):
    queue: Queue = Queue(maxsize=1)
    proc = Process(
        target=_fetch_intraday_worker,
        args=(queue, code, start_date, end_date, frequency),
        daemon=True,
    )
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        raise TimeoutError("baostock 分钟线查询超时")

    if queue.empty():
        raise RuntimeError("baostock 分钟线查询无返回")
    status, payload = queue.get()
    if status != "ok":
        raise RuntimeError(payload)
    return payload


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
    from app.services.screener_engine import _ttm_dividend_yield

    latest_daily_out = StockDailyOut.model_validate(latest_daily) if latest_daily else None
    if latest_daily_out and latest_daily_out.dividend_yield is None and latest_daily and latest_daily.close:
        dy = _ttm_dividend_yield(db, basic.code, latest_daily.close)
        if dy is not None:
            latest_daily_out = latest_daily_out.model_copy(update={"dividend_yield": dy})

    return StockDetailOut(
        code=basic.code,
        name=basic.name,
        industry=basic.industry,
        latest=latest_daily_out,
        prev_close=prev_close,
        change_pct=change_pct,
        roe=latest_fin.roe if latest_fin else None,
        revenue_yoy=latest_fin.revenue_yoy if latest_fin else None,
        profit_yoy=latest_fin.profit_yoy if latest_fin else None,
        gross_margin=latest_fin.gross_margin if latest_fin else None,
        debt_ratio=latest_fin.debt_ratio if latest_fin else None,
    )


@router.get("/{code}/quote", response_model=StockQuoteOut)
def quote(code: str, db: Session = Depends(get_db)):
    basic = db.get(StockBasic, code)
    if not basic:
        raise HTTPException(404, "股票不存在")

    from app.services.providers.quote_provider import fetch_realtime_quote_budgeted
    from app.services.screener_engine import _ttm_dividend_yield

    last2 = (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(2)
        .all()
    )
    latest = last2[0] if last2 else None
    prev_close = last2[1].close if len(last2) > 1 else None

    live = fetch_realtime_quote_budgeted(code)
    if live:
        live["name"] = live.get("name") or basic.name
        if not live.get("dividend_yield") and latest and latest.close:
            live["dividend_yield"] = _ttm_dividend_yield(db, basic.code, latest.close)
        return live

    change = None
    change_pct = None
    if latest and latest.close is not None and prev_close:
        change = latest.close - prev_close
        change_pct = change / prev_close * 100
    return StockQuoteOut(
        code=basic.code,
        name=basic.name,
        close=latest.close if latest else None,
        prev_close=prev_close,
        open=latest.open if latest else None,
        high=latest.high if latest else None,
        low=latest.low if latest else None,
        volume=latest.volume if latest else None,
        turnover=latest.turnover if latest else None,
        pe=latest.pe if latest else None,
        pb=latest.pb if latest else None,
        market_cap=latest.market_cap if latest else None,
        dividend_yield=(
            latest.dividend_yield if (latest and latest.dividend_yield is not None)
            else _ttm_dividend_yield(db, basic.code, latest.close if latest else None)
        ),
        change=change,
        change_pct=change_pct,
        source="local",
        quote_time=str(latest.trade_date) if latest else None,
    )


@router.get("/{code}/kline", response_model=list[StockDailyOut])
def kline(
    code: str,
    days: int = Query(120, ge=1, le=800),
    frequency: str = Query("d", pattern="^(d|w|m)$"),
    db: Session = Depends(get_db),
):
    """返回 K 线 OHLCV。

    日 K 使用本地 stock_daily 并按需回填；周 K/月 K 直接向 baostock 请求
    对应周期，避免前端用少量日线临时聚合导致周期语义不准。
    """
    from app.config import settings
    from app.services.data_sync import backfill_kline_single, backfill_kline_single_bs

    if not db.get(StockBasic, code):
        raise HTTPException(404, "股票不存在")

    if frequency in {"w", "m"} and settings.data_provider == "baostock":
        from app.services.providers.baostock_provider import fetch_kline

        rows = fetch_kline(
            code,
            start_date=_kline_start_date(days, frequency),
            end_date=date.today().strftime("%Y-%m-%d"),
            frequency=frequency,
        )
        return [_stock_daily_out(row) for row in rows[-days:]]

    recent_date_rows = (
        db.query(StockDaily.trade_date)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(max(days * 3, days + 20))
        .all()
    )
    have = sum(1 for (trade_date,) in recent_date_rows if trade_date and trade_date.weekday() < 5)
    if 0 < have < days:
        # 详情页优先展示已有本地数据，缺失历史在后台补齐。免费数据源
        # 偶发变慢时不应让页面同步等待几十秒。
        _queue_daily_backfill(code, days, settings.data_provider)
    elif have < days:
        if settings.data_provider == "baostock":
            backfill_kline_single_bs(db, code, days)
        else:
            backfill_kline_single(db, code, days)
    rows = (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .limit(max(days * 3, days + 20))
        .all()
    )
    # API consumers should receive chronological bars. The DB query uses DESC
    # only to keep the latest `days` rows cheap.
    latest_rows = [_stock_daily_out(row) for row in rows if _is_weekday_row(row)][:days]
    return list(reversed(latest_rows))


@router.get("/{code}/intraday", response_model=list[StockIntradayOut])
def intraday(
    code: str,
    frequency: str = Query("5", pattern="^(5|15|30|60)$"),
    days: int = Query(1, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """返回分钟 K 线。

    目前分钟线走 baostock，失败或空数据时返回 503；
    数据按需拉取，不入库，也不会用日线伪装分钟线。
    """
    basic = db.get(StockBasic, code)
    if not basic:
        raise HTTPException(404, "股票不存在")

    cached = _get_intraday_cache(code, frequency, days)
    if cached is not None:
        return cached

    end = date.today()
    # A 股只在工作日交易，往前多取一些自然日以覆盖周末/节假日。
    start = end - timedelta(days=max(days * 2 + 2, 4))
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")
    rows = []
    bs_error: Exception | None = None
    if _baostock_intraday_available():
        try:
            rows = _fetch_intraday_with_timeout(
                code,
                start_date,
                end_date,
                frequency,
                timeout=_INTRADAY_FETCH_TIMEOUT,
            )
        except (TimeoutError, RuntimeError) as exc:
            bs_error = exc
            _disable_baostock_intraday()
        if not rows:
            _disable_baostock_intraday()
    else:
        bs_error = RuntimeError("baostock 分钟线刚刚失败，已临时停用拉取，请稍后重试")

    if not rows:
        bs_msg = str(bs_error)[:80] if bs_error else "返回空数据"
        raise HTTPException(503, f"baostock 分钟线暂不可用：{bs_msg}")

    rows = sorted(rows, key=lambda item: item["datetime"])
    trade_days = []
    seen = set()
    for item in reversed(rows):
        d = item["datetime"].date()
        if d not in seen:
            trade_days.append(d)
            seen.add(d)
        if len(trade_days) >= days:
            break
    keep = set(trade_days)
    filtered_rows = [item for item in rows if item["datetime"].date() in keep]
    _set_intraday_cache(code, frequency, days, filtered_rows)
    return filtered_rows


# ----- 自选股 -----

@router.get("/me/watchlist", response_model=list[WatchlistOut])
def list_watch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Watchlist, StockBasic.name)
        .join(StockBasic, StockBasic.code == Watchlist.code)
        .filter(Watchlist.user_id == user.id)
        .all()
    )
    return [
        WatchlistOut(
            **{col.name: getattr(row.Watchlist, col.name) for col in Watchlist.__table__.columns},
            name=row.name,
        )
        for row in rows
    ]


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
