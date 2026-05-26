"""行情聚合 schemas（Dashboard 用）"""
from pydantic import BaseModel


class IndexQuote(BaseModel):
    name: str           # 上证指数
    code: str           # SH000001
    value: float        # 指数点位（直连交易所真实点位）
    change: float       # 涨跌点数
    change_pct: float   # 涨跌幅（%）
    constituents: int   # 成分股数量（DB 中前缀匹配的真实股票数）
    spark: list[float]  # 30 个交易日真实收盘价


class SectorQuote(BaseModel):
    name: str           # 行业名
    change_pct: float   # 平均涨跌（%）
    count: int          # 板块成分股数
    leader_name: str | None = None   # 板块涨幅最大成分
    leader_pct: float | None = None  # 涨幅


class MoverItem(BaseModel):
    code: str
    name: str
    industry: str | None = None
    close: float | None = None
    change_pct: float | None = None  # 涨跌幅（%）
    change: float | None = None      # 涨跌额
    amount: float | None = None      # 成交额（亿）
    turnover: float | None = None    # 换手率（%）
    pe: float | None = None
    market_cap: float | None = None  # 总市值（亿）


class MoversResponse(BaseModel):
    """四个 tab 一次性返回，前端切换零延迟"""
    gainers: list[MoverItem]   # 涨幅榜
    losers: list[MoverItem]    # 跌幅榜
    by_amount: list[MoverItem] # 成交额
    by_turnover: list[MoverItem]  # 换手率
