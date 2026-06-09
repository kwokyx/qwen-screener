from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StockBasicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    industry: str | None = None
    market: str | None = None


class StockDailyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    pe: float | None
    pb: float | None
    market_cap: float | None
    dividend_yield: float | None = None
    turnover: float | None = None


class StockIntradayOut(BaseModel):
    code: str
    datetime: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None = None


class StockQuoteOut(BaseModel):
    code: str
    name: str | None = None
    close: float | None = None
    prev_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_cap: float | None = None
    change: float | None = None
    change_pct: float | None = None
    source: str = "local"
    quote_time: str | None = None
    dividend_yield: float | None = None


class StockDetailOut(BaseModel):
    """个股详情：基本信息 + 最新行情 + 最新财务"""
    code: str
    name: str
    industry: str | None
    latest: StockDailyOut | None
    prev_close: float | None = None
    change_pct: float | None = None
    roe: float | None = None
    revenue_yoy: float | None = None
    profit_yoy: float | None = None
    gross_margin: float | None = None
    debt_ratio: float | None = None


class WatchlistCreate(BaseModel):
    code: str
    note: str | None = None
    alerts: list | None = None
    ref_price: float | None = None


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str | None = None
    note: str | None = None
    alerts: list | None = None
    ref_price: float | None = None
    created_at: datetime
