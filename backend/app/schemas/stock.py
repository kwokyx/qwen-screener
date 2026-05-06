from datetime import date

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


class StockDetailOut(BaseModel):
    """个股详情：基本信息 + 最新行情 + 最新财务"""
    code: str
    name: str
    industry: str | None
    latest: StockDailyOut | None
    roe: float | None = None
    revenue_yoy: float | None = None
    profit_yoy: float | None = None
    gross_margin: float | None = None
    debt_ratio: float | None = None


class WatchlistCreate(BaseModel):
    code: str
    note: str | None = None


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    note: str | None = None
