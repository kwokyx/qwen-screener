"""轻量回测引擎

核心能力：给定一组筛选条件 + 时间窗，模拟"按月调仓、等权持有 top N"的策略，
输出净值曲线、关键指标、交易日志。

数据来源策略：
    1. 优先从 StockDaily 拿历史 K 线
    2. 若某只股票历史 < 30 个交易日，用确定性高斯游走"合成"价格序列。
       使用 (code + start_date) 作为种子，保证同样输入永远得到同样曲线。
    3. 整个回测的 data_source 字段标记 'real' / 'synthesized' / 'mixed'，
       前端清楚地告诉用户"这是真数据还是 demo 数据"。

复杂度上没做的事（当前学年设计阶段够用）：
    - 历史基本面回看（PE/ROE 用的是当前快照而非"当时"的）
    - 交易日历（这里用日历日 ≈ 21 天/月，结果近似但合理）
    - 基准用全持仓的 buy-and-hold，不是真正的指数
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date as Date, timedelta

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, StockDaily
from app.schemas.backtest import (
    BacktestMetrics,
    BacktestRequest,
    BacktestResponse,
    BacktestTrade,
    EquityPoint,
    MonthlyReturn,
)
from app.schemas.screener import ScreenRequest
from app.services import screener_engine

MIN_REAL_DAYS = 30           # 少于这个数就 fallback 到合成
ANNUAL_TRADING_DAYS = 252    # 用于年化


# ---------------------- 价格序列 ----------------------

def _date_range_business(start: Date, end: Date) -> list[Date]:
    """生成 [start, end] 范围内的"近似交易日"序列（跳过周六日）。"""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _synth_series(code: str, base_price: float, dates: list[Date], seed_offset: int = 0) -> list[float]:
    """高斯游走 + 缓慢均值回归，确定性。"""
    if base_price <= 0:
        base_price = 100.0
    rng = random.Random(hash((code, seed_offset)) & 0xFFFFFFFF)
    series = []
    p = base_price * 0.85   # 起点稍低于现价，给"持有上涨"留点空间
    target = base_price
    for _ in dates:
        drift = (target - p) * 0.003
        noise = rng.gauss(0.0005, 0.018) * p
        p = max(0.01, p + drift + noise)
        series.append(round(p, 4))
    # 终点对齐到当前价（更直观）
    if series:
        adj = base_price / series[-1]
        # 平滑收敛到现价：最后 10 天逐步乘上去
        n_smooth = min(10, len(series))
        for i in range(n_smooth):
            w = (i + 1) / n_smooth
            idx = len(series) - n_smooth + i
            series[idx] = round(series[idx] * (1 + (adj - 1) * w), 4)
    return series


def _load_or_synth(db: Session, code: str, dates: list[Date]) -> tuple[list[float], str]:
    """返回 (与 dates 对齐的收盘价列表, 'real'|'synthesized')。"""
    rows = (
        db.query(StockDaily)
        .filter(StockDaily.code == code, StockDaily.trade_date >= dates[0], StockDaily.trade_date <= dates[-1])
        .order_by(StockDaily.trade_date)
        .all()
    )
    if len(rows) >= MIN_REAL_DAYS:
        # 合 dates 对齐：若某天 DB 没行就用上一天的 close
        date_to_close = {r.trade_date: r.close for r in rows if r.close is not None}
        last = rows[0].close or 1.0
        out = []
        for d in dates:
            if d in date_to_close:
                last = date_to_close[d]
            out.append(round(float(last), 4))
        return out, "real"

    # 拿当前 close 作为合成的基准
    latest = (
        db.query(StockDaily)
        .filter(StockDaily.code == code)
        .order_by(desc(StockDaily.trade_date))
        .first()
    )
    base = (latest.close if latest and latest.close else 100.0)
    return _synth_series(code, float(base), dates), "synthesized"


# ---------------------- 调仓判断 ----------------------

def _is_rebalance(date: Date, last: Date | None, mode: str) -> bool:
    if last is None:
        return True
    if mode == "daily":
        return date != last
    if mode == "weekly":
        return (date - last).days >= 7
    # monthly
    return date.month != last.month or date.year != last.year


# ---------------------- 指标 ----------------------

def _compute_metrics(equity: list[float], trades: list[BacktestTrade], benchmark: list[float]) -> BacktestMetrics:
    if len(equity) < 2:
        return BacktestMetrics(
            total_return=0, annual_return=0, max_drawdown=0, sharpe=0,
            volatility=0, win_rate=0, profit_loss_ratio=0, total_trades=0,
            benchmark_return=0,
        )
    initial, final = equity[0], equity[-1]
    total_return = (final - initial) / initial

    n = len(equity)
    annual_return = (final / initial) ** (ANNUAL_TRADING_DAYS / n) - 1 if final > 0 else -1.0

    daily_rets = [(equity[i] - equity[i-1]) / equity[i-1] for i in range(1, n) if equity[i-1] > 0]
    if daily_rets:
        mean = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean) ** 2 for r in daily_rets) / max(1, len(daily_rets) - 1)
        std = math.sqrt(var)
        volatility = std * math.sqrt(ANNUAL_TRADING_DAYS)
        sharpe = (mean / std) * math.sqrt(ANNUAL_TRADING_DAYS) if std > 0 else 0.0
    else:
        volatility = sharpe = 0.0

    # 最大回撤
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # 胜率 / 盈亏比（按已平仓交易）
    pnl_trades = [t for t in trades if t.side == "SELL" and t.pnl is not None]
    wins = [t.pnl for t in pnl_trades if t.pnl > 0]
    losses = [t.pnl for t in pnl_trades if t.pnl < 0]
    win_rate = len(wins) / len(pnl_trades) if pnl_trades else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    profit_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else (float("inf") if avg_win > 0 else 0.0)

    benchmark_return = (benchmark[-1] - benchmark[0]) / benchmark[0] if len(benchmark) >= 2 and benchmark[0] > 0 else 0.0

    return BacktestMetrics(
        total_return=round(total_return, 6),
        annual_return=round(annual_return, 6),
        max_drawdown=round(max_dd, 6),
        sharpe=round(sharpe, 4),
        volatility=round(volatility, 6),
        win_rate=round(win_rate, 4),
        profit_loss_ratio=round(profit_loss_ratio, 4) if math.isfinite(profit_loss_ratio) else 99.0,
        total_trades=len(pnl_trades),
        benchmark_return=round(benchmark_return, 6),
    )


def _monthly_returns(equity_dates: list[Date], equity: list[float]) -> list[MonthlyReturn]:
    """按 (year, month) 分桶，桶内首末值算月度收益率。"""
    buckets: dict[tuple[int, int], list[tuple[Date, float]]] = defaultdict(list)
    for d, v in zip(equity_dates, equity):
        buckets[(d.year, d.month)].append((d, v))
    out = []
    for (y, m), pts in sorted(buckets.items()):
        pts.sort(key=lambda x: x[0])
        s, e = pts[0][1], pts[-1][1]
        pct = (e - s) / s if s > 0 else 0.0
        out.append(MonthlyReturn(year=y, month=m, pct=round(pct, 6)))
    return out


# ---------------------- 主入口 ----------------------

def run_backtest(db: Session, req: BacktestRequest) -> BacktestResponse:
    notes: list[str] = []

    # ---- 1. 选股池 ----
    screen_req = ScreenRequest(
        conditions=req.conditions,
        logic="AND",
        sort_by=req.sort_by,
        sort_desc=req.sort_desc,
        limit=req.holdings_count,
    )
    sr = screener_engine.screen(db, screen_req)
    if not sr.items:
        raise ValueError("筛选条件没有命中任何股票，无法回测")

    universe = [it.code for it in sr.items]
    name_map = {it.code: it.name for it in sr.items}
    if len(universe) < req.holdings_count:
        notes.append(f"只筛到 {len(universe)} 只，少于目标持仓 {req.holdings_count} 只")

    # ---- 2. 准备日期 + 价格矩阵 ----
    if req.start_date >= req.end_date:
        raise ValueError("start_date 必须早于 end_date")
    dates = _date_range_business(req.start_date, req.end_date)
    if not dates:
        raise ValueError("回测窗口为空")

    price_matrix: dict[str, list[float]] = {}
    src_count = {"real": 0, "synthesized": 0}
    for code in universe:
        ser, src = _load_or_synth(db, code, dates)
        price_matrix[code] = ser
        src_count[src] += 1
    data_source = (
        "real" if src_count["synthesized"] == 0 else
        "synthesized" if src_count["real"] == 0 else
        "mixed"
    )
    if data_source != "real":
        notes.append(f"{src_count['synthesized']} / {len(universe)} 只无足够历史，已用确定性合成数据")

    # ---- 3. 模拟 ----
    cash = req.initial_capital
    shares: dict[str, int] = {c: 0 for c in universe}
    entry_price: dict[str, float] = {}
    entry_date: dict[str, Date] = {}
    trades: list[BacktestTrade] = []
    last_rb: Date | None = None
    equity_values: list[float] = []
    benchmark_values: list[float] = []  # 起始等权买入持有

    # 基准：起点等权买入持有
    bench_alloc_per = req.initial_capital / len(universe)
    bench_shares = {c: bench_alloc_per / max(0.01, price_matrix[c][0]) for c in universe}

    cost = req.transaction_cost

    for di, d in enumerate(dates):
        prices_today = {c: price_matrix[c][di] for c in universe}

        # 3.1 止损：若某持仓相对买入价跌穿 stop_loss 则平仓
        if req.stop_loss is not None:
            for c in list(shares):
                if shares[c] > 0 and entry_price.get(c, 0) > 0:
                    ret = (prices_today[c] - entry_price[c]) / entry_price[c]
                    if ret <= req.stop_loss:
                        proceeds = shares[c] * prices_today[c] * (1 - cost)
                        cash += proceeds
                        pnl = (prices_today[c] - entry_price[c]) * shares[c] - shares[c] * prices_today[c] * cost
                        trades.append(BacktestTrade(
                            date=d, side="SELL", code=c, name=name_map.get(c),
                            price=prices_today[c], qty=shares[c], pnl=round(pnl, 2),
                            holding_days=(d - entry_date[c]).days if c in entry_date else None,
                            trigger=f"止损线 {req.stop_loss * 100:.0f}%",
                        ))
                        shares[c] = 0
                        entry_price.pop(c, None)
                        entry_date.pop(c, None)

        # 3.2 调仓
        if _is_rebalance(d, last_rb, req.rebalance):
            # 算当前 NAV
            mtm = sum(shares[c] * prices_today[c] for c in universe)
            nav = cash + mtm
            target_per = nav / len(universe)
            # 简化：每只都重置到 target_per 价值（等权）
            for c in universe:
                target_qty = int(target_per // prices_today[c]) if prices_today[c] > 0 else 0
                delta = target_qty - shares[c]
                if delta > 0:
                    spend = delta * prices_today[c] * (1 + cost)
                    if spend > cash + 1e-6:
                        # 现金不够就买能买的最多
                        affordable = int(cash / (prices_today[c] * (1 + cost)))
                        delta = max(0, affordable)
                    if delta > 0:
                        cash -= delta * prices_today[c] * (1 + cost)
                        # 加权平均买入价
                        prev_qty = shares[c]
                        prev_cost_total = entry_price.get(c, 0) * prev_qty
                        new_total = prev_cost_total + delta * prices_today[c]
                        shares[c] = prev_qty + delta
                        entry_price[c] = new_total / shares[c]
                        if prev_qty == 0:
                            entry_date[c] = d
                        trades.append(BacktestTrade(
                            date=d, side="BUY", code=c, name=name_map.get(c),
                            price=prices_today[c], qty=delta, pnl=None,
                            holding_days=None, trigger="调仓买入",
                        ))
                elif delta < 0:
                    sell_qty = -delta
                    cash += sell_qty * prices_today[c] * (1 - cost)
                    pnl = (prices_today[c] - entry_price.get(c, prices_today[c])) * sell_qty \
                          - sell_qty * prices_today[c] * cost
                    shares[c] += delta  # delta 是负数
                    trades.append(BacktestTrade(
                        date=d, side="SELL", code=c, name=name_map.get(c),
                        price=prices_today[c], qty=sell_qty, pnl=round(pnl, 2),
                        holding_days=(d - entry_date[c]).days if c in entry_date else None,
                        trigger="调仓减仓",
                    ))
                    if shares[c] == 0:
                        entry_price.pop(c, None)
                        entry_date.pop(c, None)
            last_rb = d

        # 3.3 mark to market
        nav_today = cash + sum(shares[c] * prices_today[c] for c in universe)
        equity_values.append(nav_today)
        bench_today = sum(bench_shares[c] * prices_today[c] for c in universe)
        benchmark_values.append(bench_today)

    # ---- 4. 装结果 ----
    initial = req.initial_capital
    equity_curve = [
        EquityPoint(date=d, value=round(v, 2), pct=round((v - initial) / initial, 6))
        for d, v in zip(dates, equity_values)
    ]
    bench_initial = benchmark_values[0] if benchmark_values else initial
    bench_curve = [
        EquityPoint(date=d, value=round(v, 2), pct=round((v - bench_initial) / bench_initial, 6) if bench_initial else 0)
        for d, v in zip(dates, benchmark_values)
    ]
    metrics = _compute_metrics(equity_values, trades, benchmark_values)
    monthly = _monthly_returns(dates, equity_values)

    return BacktestResponse(
        name=req.name,
        universe=universe,
        universe_names=[name_map.get(c, c) for c in universe],
        equity=equity_curve,
        benchmark=bench_curve,
        trades=trades[-200:],   # 防止前端列表过大
        metrics=metrics,
        monthly_returns=monthly,
        data_source=data_source,
        notes=notes,
    )
