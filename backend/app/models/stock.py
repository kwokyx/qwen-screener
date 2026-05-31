from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockBasic(Base):
    """股票基本信息表（A 股全量）"""
    __tablename__ = "stock_basic"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)  # 600000.SH
    name: Mapped[str] = mapped_column(String(64), index=True)
    industry: Mapped[str | None] = mapped_column(String(64), index=True)
    market: Mapped[str | None] = mapped_column(String(16))  # 主板/创业板/科创板
    list_date: Mapped[date | None] = mapped_column(Date)
    total_share: Mapped[float | None] = mapped_column(Float)  # 总股本（亿）
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StockDaily(Base):
    """日线行情 + 估值指标"""
    __tablename__ = "stock_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)        # 市盈率 TTM
    pb: Mapped[float | None] = mapped_column(Float)        # 市净率
    market_cap: Mapped[float | None] = mapped_column(Float)  # 总市值（亿）
    turnover: Mapped[float | None] = mapped_column(Float)  # 换手率
    dividend_yield: Mapped[float | None] = mapped_column(Float)  # 股息率 TTM (% )

    __table_args__ = (Index("ix_code_date", "code", "trade_date", unique=True),)


class StockFinancial(Base):
    """财务指标（按报告期）"""
    __tablename__ = "stock_financial"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    roe: Mapped[float | None] = mapped_column(Float)            # 净资产收益率
    net_profit: Mapped[float | None] = mapped_column(Float)     # 净利润（亿）
    revenue: Mapped[float | None] = mapped_column(Float)        # 营业收入（亿）
    revenue_yoy: Mapped[float | None] = mapped_column(Float)    # 营收同比
    profit_yoy: Mapped[float | None] = mapped_column(Float)     # 净利同比
    gross_margin: Mapped[float | None] = mapped_column(Float)   # 毛利率
    debt_ratio: Mapped[float | None] = mapped_column(Float)     # 资产负债率

    __table_args__ = (Index("ix_code_report", "code", "report_date", unique=True),)


class StockDividend(Base):
    """已实施的现金分红记录，用于本地计算最近 12 个月股息率。"""
    __tablename__ = "stock_dividend"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    operate_date: Mapped[date] = mapped_column(Date, index=True)  # 除权除息日
    cash_per_share: Mapped[float] = mapped_column(Float)  # 税前每股现金分红
    notice_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        Index("ix_dividend_code_operate_cash", "code", "operate_date", "cash_per_share", unique=True),
    )
