"""行情聚合接口（Dashboard 三块卡片）。

数据全部来自 StockBasic + StockDaily 的最新一天快照；今日涨跌幅由 (close-open)/open 推算。
现阶段 DB 只存"当日"快照，所以指数 / 板块的 30 日 sparkline 用确定性合成。
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockBasic, StockDaily
from app.schemas.market import (
    IndexQuote,
    MoverItem,
    MoversResponse,
    SectorQuote,
)


router = APIRouter(prefix="/market", tags=["market"])


# ---------------------- 指数定义 ----------------------
# 用代码前缀粗略归类四大指数；anchor_value 是惯例点位，方便前端不显得"小"。
# change_pct 由该集合内股票的市值加权平均计算，real。
INDEX_DEFS = [
    {"name": "上证指数", "code": "SH000001", "anchor": 3186.42, "match": lambda c: c.startswith("60") or c.startswith("68")},
    {"name": "深证成指", "code": "SZ399001", "anchor": 10524.18, "match": lambda c: c.startswith("00") or c.startswith("30")},
    {"name": "创业板指", "code": "SZ399006", "anchor": 2148.62, "match": lambda c: c.startswith("30")},
    {"name": "科创50",   "code": "SH000688", "anchor": 962.45,   "match": lambda c: c.startswith("688")},
]


def _latest_trade_date(db: Session) -> Date | None:
    return db.query(func.max(StockDaily.trade_date)).scalar()


def _change_pct(open_p: float | None, close_p: float | None) -> float | None:
    if open_p is None or close_p is None or open_p <= 0:
        return None
    return (close_p - open_p) / open_p * 100.0


def _spark(seed_key: str, anchor: float, current_change_pct: float, n: int = 30) -> list[float]:
    """围绕 anchor 做高斯游走，最后一点对齐到 anchor*(1+change/100)。确定性。"""
    rng = random.Random(hash(seed_key) & 0xFFFFFFFF)
    p = anchor
    series = []
    for _ in range(n):
        p = max(0.01, p * (1 + rng.gauss(0, 0.006)))
        series.append(p)
    target = anchor * (1 + current_change_pct / 100.0)
    if series:
        adj = target / series[-1]
        # 平滑收敛：最后 5 点逐渐拉到 target
        n_smooth = min(5, len(series))
        for i in range(n_smooth):
            w = (i + 1) / n_smooth
            idx = len(series) - n_smooth + i
            series[idx] = series[idx] * (1 + (adj - 1) * w)
    return [round(v, 2) for v in series]


# ---------------------- /market/indices ----------------------

@router.get("/indices", response_model=list[IndexQuote])
def get_indices(db: Session = Depends(get_db)):
    """4 大指数：流通市值加权 × 真涨跌幅（close vs prev_close）。
    冷启动只有一天数据时退回盘中口径 (close-open)/open。
    """
    last_dates = (
        db.query(StockDaily.trade_date).distinct()
        .order_by(desc(StockDaily.trade_date)).limit(2).all()
    )
    if not last_dates:
        return []
    td = last_dates[0][0]
    prev_td = last_dates[1][0] if len(last_dates) > 1 else None

    rows = (
        db.query(StockDaily.code, StockDaily.trade_date,
                 StockDaily.open, StockDaily.close, StockDaily.market_cap)
        .filter(StockDaily.trade_date.in_([d for d in (td, prev_td) if d is not None]))
        .all()
    )

    # 按 code 拼最新与前一日数据
    by_code: dict[str, dict] = {}
    for code, t, open_p, close_p, mc in rows:
        rec = by_code.setdefault(code, {})
        if t == td:
            rec["open"] = open_p
            rec["close"] = close_p
            rec["mc"] = mc
        elif prev_td is not None and t == prev_td:
            rec["prev_close"] = close_p

    pool = []  # (code, mc, change_pct)
    for code, d in by_code.items():
        close_p = d.get("close")
        mc = d.get("mc")
        if close_p is None or not mc or mc <= 0:
            continue
        prev = d.get("prev_close")
        if prev and prev > 0:
            cp = (close_p - prev) / prev * 100
        else:
            cp = _change_pct(d.get("open"), close_p)
            if cp is None:
                continue
        pool.append((code, mc, cp))

    out: list[IndexQuote] = []
    for d in INDEX_DEFS:
        members = [(c, cap, cp) for c, cap, cp in pool if d["match"](c)]
        if not members:
            continue
        cap_sum = sum(m[1] for m in members)
        change_pct = sum(m[1] * m[2] for m in members) / cap_sum
        value = d["anchor"] * (1 + change_pct / 100.0)
        change = value - d["anchor"]
        out.append(IndexQuote(
            name=d["name"],
            code=d["code"],
            value=round(value, 2),
            change=round(change, 2),
            change_pct=round(change_pct, 2),
            constituents=len(members),
            spark=_spark(d["code"] + str(td), d["anchor"], change_pct),
        ))
    return out


# ---------------------- /market/sectors ----------------------

@router.get("/sectors", response_model=list[SectorQuote])
def get_sectors(limit: int = Query(default=8, ge=1, le=30), db: Session = Depends(get_db)):
    """行业涨跌幅：流通市值加权平均，跨日 (close vs prev_close)。

    若 DB 只存了 1 个交易日（冷启动），退回 (close - open) / open 这个盘中口径，
    并把所有股票按等权处理；运行 ≥ 2 日后自动用真实涨跌幅 + 市值加权。
    """
    # 拉最近两个交易日
    last_dates = (
        db.query(StockDaily.trade_date)
        .distinct()
        .order_by(desc(StockDaily.trade_date))
        .limit(2)
        .all()
    )
    if not last_dates:
        return []
    td = last_dates[0][0]
    prev_td = last_dates[1][0] if len(last_dates) > 1 else None

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
    return out[:limit]


# ---------------------- /market/movers ----------------------

def _rows_to_movers(rows) -> list[MoverItem]:
    out = []
    for r in rows:
        cp = _change_pct(r.open, r.close)
        if cp is None:
            continue
        out.append(MoverItem(
            code=r.code,
            name=r.name,
            industry=r.industry,
            close=r.close,
            change=round((r.close - r.open) if r.open is not None else 0, 2),
            change_pct=round(cp, 2),
            amount=round(r.amount / 1e8, 2) if r.amount else None,
            turnover=round(r.turnover, 2) if r.turnover is not None else None,
            pe=round(r.pe, 2) if r.pe is not None else None,
            market_cap=round(r.market_cap, 2) if r.market_cap is not None else None,
        ))
    return out


@router.get("/movers", response_model=MoversResponse)
def get_movers(limit: int = Query(default=8, ge=1, le=50), db: Session = Depends(get_db)):
    td = _latest_trade_date(db)
    if td is None:
        return MoversResponse(gainers=[], losers=[], by_amount=[], by_turnover=[])

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
    items = _rows_to_movers(all_rows)
    gainers = sorted(items, key=lambda x: -(x.change_pct or 0))[:limit]
    losers  = sorted(items, key=lambda x:  (x.change_pct or 0))[:limit]

    # 成交额 / 换手率 SQL 排序更高效
    by_amount_rows = base.order_by(desc(StockDaily.amount)).limit(limit).all()
    by_amount = _rows_to_movers(by_amount_rows)

    by_turn_rows = base.order_by(desc(StockDaily.turnover)).limit(limit).all()
    by_turnover = _rows_to_movers(by_turn_rows)

    return MoversResponse(
        gainers=gainers, losers=losers,
        by_amount=by_amount, by_turnover=by_turnover,
    )


# ---------------------- /market/ticker ----------------------

@router.get("/ticker")
def get_ticker(db: Session = Depends(get_db)):
    """Ticker 条用的简化数据：4 大指数 + 几个聚合数字。"""
    indices = get_indices(db)
    td = _latest_trade_date(db)

    # 全市场总成交额 + 上涨/下跌只数
    rows = (
        db.query(StockDaily.open, StockDaily.close, StockDaily.amount)
        .filter(StockDaily.trade_date == td)
        .all()
    )
    total_amount = 0.0
    n_up = n_dn = 0
    for o, c, a in rows:
        if a is not None:
            total_amount += a
        cp = _change_pct(o, c)
        if cp is None:
            continue
        if cp > 0:
            n_up += 1
        elif cp < 0:
            n_dn += 1

    return {
        "indices": [i.model_dump() for i in indices],
        "total_amount_yi": round(total_amount / 1e8, 0),  # 全市场成交额（亿）
        "advancers": n_up,
        "decliners": n_dn,
        "trade_date": str(td) if td else None,
    }
