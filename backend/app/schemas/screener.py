from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.stock import StockBasicOut


Operator = Literal["gt", "gte", "lt", "lte", "eq", "between", "in"]

# 支持的筛选字段（前端下拉框、千问 prompt 共用）
ALLOWED_FIELDS = {
    "pe", "pb", "roe", "market_cap", "dividend_yield",
    "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio",
    "industry", "market", "close", "turnover",
}


class FilterCondition(BaseModel):
    field: str = Field(description="筛选字段，如 pe / roe / industry")
    op: Operator
    value: float | int | str | list = Field(description="阈值；between 传 [低, 高]，in 传列表")


class ScreenRequest(BaseModel):
    conditions: list[FilterCondition] = Field(default_factory=list)
    logic: Literal["AND", "OR"] = "AND"
    sort_by: str | None = None
    sort_desc: bool = True
    limit: int = Field(default=50, ge=1, le=500)


class NLScreenRequest(BaseModel):
    """自然语言筛选请求"""
    query: str = Field(min_length=1, max_length=500, description="用户自然语言，如：低估值高分红的银行股")


class ScreenResultItem(StockBasicOut):
    trade_date: date | None = None
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    market_cap: float | None = None
    dividend_yield: float | None = None
    close: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    turnover: float | None = None
    revenue_yoy: float | None = None
    profit_yoy: float | None = None
    gross_margin: float | None = None
    debt_ratio: float | None = None


class ScreenResponse(BaseModel):
    total: int
    items: list[ScreenResultItem]
    parsed_conditions: list[FilterCondition] | None = None  # NL 模式回显
    explanation: str | None = None  # 千问对结果的简短解读
