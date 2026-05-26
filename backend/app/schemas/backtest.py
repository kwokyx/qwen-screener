"""回测引擎请求 / 响应 schema"""
from __future__ import annotations

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.screener import FilterCondition


class BacktestRequest(BaseModel):
    name: str = Field(default="未命名策略", max_length=60)
    # 通过 conditions 选股；与 screener 同一套字段
    conditions: list[FilterCondition] = Field(default_factory=list)
    sort_by: str | None = "market_cap"
    sort_desc: bool = True
    holdings_count: int = Field(default=10, ge=1, le=50, description="持仓只数（取筛选 top N）")
    weighting: Literal["equal", "cap"] = "equal"

    start_date: Date
    end_date: Date
    initial_capital: float = Field(default=1_000_000, gt=0)
    rebalance: Literal["daily", "weekly", "monthly"] = "monthly"
    transaction_cost: float = Field(default=0.003, ge=0, le=0.05, description="单边交易成本，0.003 = 千三")
    stop_loss: float | None = Field(default=-0.15, description="止损线，例 -0.15 表示 -15%；None 关闭")


class EquityPoint(BaseModel):
    date: Date
    value: float          # 当日净值（绝对金额）
    pct: float            # 自起始的累计收益率


class BacktestTrade(BaseModel):
    date: Date
    side: Literal["BUY", "SELL"]
    code: str
    name: str | None = None
    price: float
    qty: int
    pnl: float | None = None    # 仅卖出时填写
    holding_days: int | None = None
    trigger: str


class MonthlyReturn(BaseModel):
    year: int
    month: int
    pct: float


class BacktestMetrics(BaseModel):
    total_return: float       # 累计收益率
    annual_return: float      # 年化
    max_drawdown: float       # 最大回撤（负数）
    sharpe: float             # 夏普
    volatility: float         # 年化波动率
    win_rate: float           # 胜率（基于交易笔数）
    profit_loss_ratio: float  # 盈亏比
    total_trades: int
    benchmark_return: float   # 基准累计收益率


class BacktestResponse(BaseModel):
    name: str
    universe: list[str]                       # 选出的股票代码
    universe_names: list[str]                 # 名称
    equity: list[EquityPoint]
    benchmark: list[EquityPoint]              # 基准等权"买入持有"参考曲线
    trades: list[BacktestTrade]
    metrics: BacktestMetrics
    monthly_returns: list[MonthlyReturn]
    data_source: Literal["real", "synthesized", "mixed"]
    notes: list[str] = Field(default_factory=list)
