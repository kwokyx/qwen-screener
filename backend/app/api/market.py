"""行情聚合接口（Dashboard 三块卡片）。

- 指数：直连 akshare stock_zh_index_daily 拿真实点位 + 30 日折线，1h Redis 缓存
- 板块 / 涨跌榜：DB 里 StockBasic + StockDaily 聚合，change_pct 用 prev_close + 流通市值加权
"""
from __future__ import annotations

import copy
import threading
import time
from collections import defaultdict
from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily
from app.schemas.market import (
    IndexQuote,
    MoverItem,
    MoversResponse,
    SectorQuote,
)
from app.services import cache as _cache


router = APIRouter(prefix="/market", tags=["market"])
_LOCAL_MARKET_CACHE_TTL = 120.0
_local_market_cache_lock = threading.Lock()
_local_market_cache: dict[tuple, tuple[float, object]] = {}


# 4 大指数：内部 code → akshare symbol
INDEX_DEFS = [
    {"name": "上证指数", "code": "SH000001", "ak": "sh000001", "prefixes": ("60", "68"), "constituents_match": lambda c: c.startswith("60") or c.startswith("68")},
    {"name": "深证成指", "code": "SZ399001", "ak": "sz399001", "prefixes": ("00", "30"), "constituents_match": lambda c: c.startswith("00") or c.startswith("30")},
    {"name": "创业板指", "code": "SZ399006", "ak": "sz399006", "prefixes": ("30",), "constituents_match": lambda c: c.startswith("30")},
    {"name": "科创50",   "code": "SH000688", "ak": "sh000688", "prefixes": ("688",), "constituents_match": lambda c: c.startswith("688")},
]


def _min_market_rows(db: Session) -> int:
    """Minimum rows for a date to be treated as a market-wide snapshot.

    Detail-page lazy K-line backfills can insert fresh rows for only one or two
    stocks. Those dates are valid for the individual stock, but they must not
    become the "latest market date" for dashboard/movers/ticker calculations.
    """
    basic_cnt = db.query(StockBasic).count()
    return max(100, int(basic_cnt * 0.5)) if basic_cnt else 100


def _covered_trade_dates(db: Session, limit: int = 2) -> list[Date]:
    cache_key = ("covered_trade_dates", limit)
    cached = _local_cache_get(cache_key)
    if cached is not None:
        return cached

    cnt = func.count(StockDaily.id)
    rows = (
        db.query(StockDaily.trade_date, cnt.label("n"))
        .group_by(StockDaily.trade_date)
        .having(cnt >= _min_market_rows(db))
        .order_by(desc(StockDaily.trade_date))
        .limit(limit)
        .all()
    )
    if rows:
        dates = [r[0] for r in rows]
        _local_cache_set(cache_key, dates)
        return dates
    dates = [
        r[0] for r in (
            db.query(StockDaily.trade_date)
            .distinct()
            .order_by(desc(StockDaily.trade_date))
            .limit(limit)
            .all()
        )
    ]
    _local_cache_set(cache_key, dates)
    return dates


def _latest_trade_date(db: Session) -> Date | None:
    dates = _covered_trade_dates(db, limit=1)
    return dates[0] if dates else None


def _local_cache_get(key: tuple):
    with _local_market_cache_lock:
        item = _local_market_cache.get(key)
        if not item:
            return None
        expires_at, payload = item
        if time.monotonic() >= expires_at:
            _local_market_cache.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _local_cache_set(key: tuple, payload, ttl: float = _LOCAL_MARKET_CACHE_TTL):
    with _local_market_cache_lock:
        _local_market_cache[key] = (time.monotonic() + ttl, copy.deepcopy(payload))


def clear_market_cache() -> None:
    """Invalidate dashboard market aggregate caches after local market data changes."""
    with _local_market_cache_lock:
        _local_market_cache.clear()
    _cache.delete_prefix("qwen:indices_local_v2:")


def _change_pct(open_p: float | None, close_p: float | None, prev_close: float | None = None) -> float | None:
    base = prev_close if prev_close and prev_close > 0 else open_p
    if base is None or close_p is None or base <= 0:
        return None
    return (close_p - base) / base * 100.0


def _fetch_index_real(ak_symbol: str, days: int = 30) -> dict | None:
    """直连 akshare 拉真实指数日线，返回 {value, change, change_pct, spark, count}。
    数据由 1h Redis 缓存包裹，调用方走 _real_indices()。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=ak_symbol)
    except Exception as e:
        logger.warning("[INDEX] {} 拉取失败: {}", ak_symbol, str(e)[:120])
        return None
    if df is None or df.empty or len(df) < 2:
        return None
    tail = df.tail(days)
    closes = [round(float(v), 2) for v in tail["close"].tolist()]
    if len(closes) < 2:
        return None
    latest = closes[-1]
    prev = closes[-2]
    change = round(latest - prev, 2)
    change_pct = round((latest - prev) / prev * 100, 2) if prev > 0 else 0.0
    return {
        "value": latest,
        "change": change,
        "change_pct": change_pct,
        "spark": closes,
    }


def _real_indices() -> dict[str, dict]:
    """4 大指数完整快照，1h Redis 缓存。"""
    key = _cache.make_key("indices_real_v1", "all")
    cached = _cache.get_json(key)
    if cached:
        return cached
    return {}


def _local_indices(db: Session, days: int = 30) -> list[IndexQuote]:
    """Use local stock_daily rows to build a fast dashboard snapshot.

    This keeps the frontend usable when live index providers are slow or blocked.
    It is intentionally lightweight and only used as a display fallback.
    """
    dates = _covered_trade_dates(db, limit=days)
    if not dates:
        return []

    out: list[IndexQuote] = []
    asc_dates = sorted(dates)
    latest = max(dates)
    prev_dates = [d for d in asc_dates if d < latest]
    prev = prev_dates[-1] if prev_dates else None

    for d in INDEX_DEFS:
        stats = _index_prefix_stats(db, dates, d["prefixes"])
        spark: list[float] = []
        latest_value = None
        prev_value = None
        constituents = 0

        for td in asc_dates:
            stat = stats.get(td)
            if not stat or not stat["avg_close"] or stat["count"] <= 0:
                continue
            avg_close = float(stat["avg_close"])
            value = round(avg_close * 100, 2)
            spark.append(value)
            if td == latest:
                latest_value = value
                constituents = int(stat["count"])
            if prev is not None and td == prev:
                prev_value = value

        if latest_value is None:
            continue
        if prev_value is None:
            stat = stats.get(latest)
            prev_value = (
                round(float(stat["avg_open"]) * 100, 2)
                if stat and stat["avg_open"]
                else latest_value
            )

        change = round(latest_value - prev_value, 2)
        change_pct = round((latest_value - prev_value) / prev_value * 100, 2) if prev_value else 0.0
        out.append(IndexQuote(
            name=d["name"],
            code=d["code"],
            value=latest_value,
            change=change,
            change_pct=change_pct,
            constituents=constituents,
            spark=spark[-days:],
        ))

    return out


def _index_prefix_stats(db: Session, dates: list[Date], prefixes: tuple[str, ...]) -> dict[Date, dict]:
    """Aggregate index-like local snapshots with code-range scans.

    SQLite does not consistently use the existing ``(code, trade_date)`` index
    for ``LIKE '60%'`` queries, which made cold dashboard index calculation
    scan the recent daily rows once per index. Range predicates keep the query
    on the code index and then combine multi-prefix indices with weighted
    averages.
    """
    stats: dict[Date, dict] = {}
    for prefix in prefixes:
        for trade_date, avg_close, avg_open, count in (
            db.query(
                StockDaily.trade_date,
                func.avg(StockDaily.close),
                func.avg(StockDaily.open),
                func.count(StockDaily.id),
            )
            .filter(
                StockDaily.trade_date.in_(dates),
                StockDaily.close.isnot(None),
                _code_prefix_range_filter(prefix),
            )
            .group_by(StockDaily.trade_date)
            .all()
        ):
            if not count:
                continue
            rec = stats.setdefault(trade_date, {
                "close_sum": 0.0,
                "open_sum": 0.0,
                "count": 0,
            })
            rec["close_sum"] += float(avg_close or 0) * int(count)
            rec["open_sum"] += float(avg_open or 0) * int(count)
            rec["count"] += int(count)

    return {
        trade_date: {
            "avg_close": rec["close_sum"] / rec["count"],
            "avg_open": rec["open_sum"] / rec["count"],
            "count": rec["count"],
        }
        for trade_date, rec in stats.items()
        if rec["count"] > 0
    }


def _code_prefix_range_filter(prefix: str):
    return and_(StockDaily.code >= prefix, StockDaily.code < _prefix_upper_bound(prefix))


def _prefix_upper_bound(prefix: str) -> str:
    if not prefix or not prefix.isdigit():
        return f"{prefix}\uffff"
    return str(int(prefix) + 1).zfill(len(prefix))


# ---------------------- /market/indices ----------------------

@router.get("/indices", response_model=list[IndexQuote])
def get_indices(db: Session = Depends(get_db)):
    """4 大指数：优先返回已缓存的真实指数；没有缓存时用本地 DB 快速估算。

    不在页面请求链路里实时访问 akshare，避免外部源站慢导致前端一直 loading。
    """
    real = _real_indices()
    if not real:
        latest = _latest_trade_date(db)
        local_key = ("indices", str(latest))
        local_cached = _local_cache_get(local_key)
        if local_cached is not None:
            return [IndexQuote(**item) for item in local_cached]
        cache_key = _cache.make_key("indices_local_v2", str(latest))
        cached = _cache.get_json(cache_key)
        if cached:
            _local_cache_set(local_key, cached)
            return [IndexQuote(**item) for item in cached]
        local = _local_indices(db)
        if local:
            payload = [item.model_dump() for item in local]
            _local_cache_set(local_key, payload)
            _cache.set_json(cache_key, payload, ttl=600)
        return local

    # constituents 数（基于内部 DB，按代码前缀粗略统计）
    latest = _latest_trade_date(db)
    real_key = ("indices_real", str(latest))
    real_cached = _local_cache_get(real_key)
    if real_cached is not None:
        return [IndexQuote(**item) for item in real_cached]
    rows = db.query(StockDaily.code).filter(StockDaily.trade_date == latest).all() if real else []
    codes = [r[0] for r in rows]

    out: list[IndexQuote] = []
    for d in INDEX_DEFS:
        snap = real.get(d["code"])
        if not snap:
            continue
        constituents = sum(1 for c in codes if d["constituents_match"](c.split(".")[0]))
        out.append(IndexQuote(
            name=d["name"], code=d["code"],
            value=snap["value"], change=snap["change"], change_pct=snap["change_pct"],
            constituents=constituents,
            spark=snap["spark"],
        ))
    _local_cache_set(real_key, [item.model_dump() for item in out])
    return out


# ---------------------- /market/sectors ----------------------

@router.get("/sectors", response_model=list[SectorQuote])
def get_sectors(limit: int = Query(default=8, ge=1, le=30), db: Session = Depends(get_db)):
    """行业涨跌幅：流通市值加权平均，跨日 (close vs prev_close)。

    若 DB 只存了 1 个交易日（冷启动），退回 (close - open) / open 这个盘中口径，
    并把所有股票按等权处理；运行 ≥ 2 日后自动用真实涨跌幅 + 市值加权。
    """
    # 拉最近两个覆盖率足够高的交易日，避免单股懒加载日期污染全市场统计
    last_dates = [(d,) for d in _covered_trade_dates(db, limit=2)]
    if not last_dates:
        return []
    td = last_dates[0][0]
    prev_td = last_dates[1][0] if len(last_dates) > 1 else None
    cache_key = ("sectors", str(td), str(prev_td), limit)
    cached = _local_cache_get(cache_key)
    if cached is not None:
        return [SectorQuote(**item) for item in cached]

    # 拉这两天的所有数据（带 open/close 兜底 + market_cap 加权）
    rows = (
        db.query(
            StockBasic.industry, StockBasic.code, StockBasic.name,
            StockDaily.trade_date, StockDaily.open, StockDaily.close, StockDaily.market_cap,
        )
        .join(StockDaily, StockBasic.code == StockDaily.code)
        .filter(StockBasic.industry.isnot(None))
        .filter(StockDaily.trade_date.in_([d for d in (td, prev_td) if d is not None]))
        .all()
    )

    # 按 code 收齐两天数据，算各股 change_pct
    by_code: dict[str, dict] = {}
    for industry, code, name, t, open_p, close_p, mc in rows:
        rec = by_code.setdefault(code, {"industry": industry, "name": name})
        if t == td:
            rec["close"] = close_p
            rec["open"] = open_p
            rec["mc"] = mc
        elif prev_td is not None and t == prev_td:
            rec["prev_close"] = close_p

    bucket: dict[str, list] = defaultdict(list)
    for code, d in by_code.items():
        close_p = d.get("close")
        if close_p is None:
            continue
        prev = d.get("prev_close")
        if prev and prev > 0:
            cp = (close_p - prev) / prev * 100   # 真涨跌幅，含跳空
        else:
            cp = _change_pct(d.get("open"), close_p)  # 冷启动兜底（盘中）
            if cp is None:
                continue
        bucket[d["industry"]].append({
            "code": code, "name": d["name"], "change_pct": cp, "mc": d.get("mc"),
        })

    out: list[SectorQuote] = []
    for industry, items in bucket.items():
        if not items:
            continue
        # 流通市值加权；若全部无 mc 则等权回退
        total_mc = sum((it["mc"] or 0) for it in items)
        if total_mc > 0:
            weighted = sum(it["change_pct"] * (it["mc"] or 0) for it in items) / total_mc
        else:
            weighted = sum(it["change_pct"] for it in items) / len(items)
        leader = max(items, key=lambda x: x["change_pct"])
        out.append(SectorQuote(
            name=industry,
            change_pct=round(weighted, 2),
            count=len(items),
            leader_name=leader["name"],
            leader_pct=round(leader["change_pct"], 2),
        ))

    out.sort(key=lambda s: -abs(s.change_pct))
    payload = [item.model_dump() for item in out[:limit]]
    _local_cache_set(cache_key, payload)
    return [SectorQuote(**item) for item in payload]


# ---------------------- /market/movers ----------------------

def _rows_to_movers(rows, prev_close_by_code: dict[str, float] | None = None) -> list[MoverItem]:
    prev_close_by_code = prev_close_by_code or {}
    out = []
    for r in rows:
        prev_close = prev_close_by_code.get(r.code)
        cp = _change_pct(r.open, r.close, prev_close)
        if cp is None:
            continue
        change = (r.close - prev_close) if prev_close is not None else ((r.close - r.open) if r.open is not None else 0)
        out.append(MoverItem(
            code=r.code,
            name=r.name,
            industry=r.industry,
            close=r.close,
            change=round(change, 2),
            change_pct=round(cp, 2),
            amount=round(r.amount / 1e8, 2) if r.amount else None,
            turnover=round(r.turnover, 2) if r.turnover is not None else None,
            pe=round(r.pe, 2) if r.pe is not None else None,
            market_cap=round(r.market_cap, 2) if r.market_cap is not None else None,
        ))
    return out


@router.get("/movers", response_model=MoversResponse)
def get_movers(limit: int = Query(default=8, ge=1, le=50), db: Session = Depends(get_db)):
    dates = _covered_trade_dates(db, limit=2)
    td = dates[0] if dates else None
    if td is None:
        return MoversResponse(gainers=[], losers=[], by_amount=[], by_turnover=[])
    prev_td = dates[1] if len(dates) > 1 else None
    cache_key = ("movers", str(td), str(prev_td), limit)
    cached = _local_cache_get(cache_key)
    if cached is not None:
        return MoversResponse(**cached)
    prev_close_by_code = {}
    if prev_td is not None:
        prev_close_by_code = {
            code: close for code, close in db.query(StockDaily.code, StockDaily.close)
            .filter(StockDaily.trade_date == prev_td, StockDaily.close.isnot(None))
            .all()
        }

    base = (
        db.query(
            StockBasic.code, StockBasic.name, StockBasic.industry,
            StockDaily.open, StockDaily.close, StockDaily.amount,
            StockDaily.turnover, StockDaily.pe, StockDaily.market_cap,
        )
        .join(StockDaily, StockBasic.code == StockDaily.code)
        .filter(StockDaily.trade_date == td, StockDaily.open.isnot(None), StockDaily.close.isnot(None))
    )

    # 涨幅 / 跌幅 都用 change_pct 排序，但 SQL 里没字段，先在 Python 排
    all_rows = base.all()
    items = _rows_to_movers(all_rows, prev_close_by_code)
    gainers = sorted(items, key=lambda x: -(x.change_pct or 0))[:limit]
    losers  = sorted(items, key=lambda x:  (x.change_pct or 0))[:limit]

    # 成交额 / 换手率 SQL 排序更高效
    by_amount_rows = base.order_by(desc(StockDaily.amount)).limit(limit).all()
    by_amount = _rows_to_movers(by_amount_rows, prev_close_by_code)

    by_turn_rows = base.order_by(desc(StockDaily.turnover)).limit(limit).all()
    by_turnover = _rows_to_movers(by_turn_rows, prev_close_by_code)

    response = MoversResponse(
        gainers=gainers, losers=losers,
        by_amount=by_amount, by_turnover=by_turnover,
    )
    _local_cache_set(cache_key, response.model_dump())
    return response


# ---------------------- /market/ticker ----------------------

@router.get("/ticker")
def get_ticker(db: Session = Depends(get_db)):
    """Ticker 条用的简化数据：4 大指数 + 几个聚合数字。"""
    dates = _covered_trade_dates(db, limit=2)
    td = dates[0] if dates else None
    prev_td = dates[1] if len(dates) > 1 else None
    cache_key = ("ticker", str(td), str(prev_td))
    cached = _local_cache_get(cache_key)
    if cached is not None:
        return cached
    indices = get_indices(db)
    prev_close_by_code = {}
    if prev_td is not None:
        prev_close_by_code = {
            code: close for code, close in db.query(StockDaily.code, StockDaily.close)
            .filter(StockDaily.trade_date == prev_td, StockDaily.close.isnot(None))
            .all()
        }

    # 全市场总成交额 + 上涨/下跌只数
    rows = (
        db.query(StockDaily.code, StockDaily.open, StockDaily.close, StockDaily.amount)
        .filter(StockDaily.trade_date == td)
        .all()
    )
    total_amount = 0.0
    n_up = n_dn = 0
    for code, o, c, a in rows:
        if a is not None:
            total_amount += a
        cp = _change_pct(o, c, prev_close_by_code.get(code))
        if cp is None:
            continue
        if cp > 0:
            n_up += 1
        elif cp < 0:
            n_dn += 1

    payload = {
        "indices": [i.model_dump() for i in indices],
        "total_amount_yi": round(total_amount / 1e8, 0),  # 全市场成交额（亿）
        "advancers": n_up,
        "decliners": n_dn,
        "trade_date": str(td) if td else None,
    }
    _local_cache_set(cache_key, payload)
    return payload


def warm_market_cache() -> None:
    """Precompute dashboard market aggregates after backend startup.

    The first dashboard request should not pay the cold local-aggregation cost.
    This is best-effort and intentionally keeps failures out of the user path.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        get_indices(db)
        get_sectors(20, db)
        get_movers(10, db)
        get_ticker(db)
        logger.info("[MARKET] 本地行情概览缓存预热完成")
    except Exception as exc:
        logger.warning("[MARKET] 本地行情概览缓存预热失败: {}", str(exc)[:160])
    finally:
        db.close()
