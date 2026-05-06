"""传统多条件筛选引擎

将 FilterCondition 列表翻译成 SQLAlchemy 查询。这一层不依赖千问，
是系统的"基础筛选模块"，论文里独立成章。
"""
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, StockDaily, StockFinancial
from app.schemas.screener import (
    ALLOWED_FIELDS,
    FilterCondition,
    ScreenRequest,
    ScreenResponse,
    ScreenResultItem,
)


# 字段 → ORM 列映射。前端/千问只能引用这里列出的字段。
FIELD_MAP = {
    "pe": StockDaily.pe,
    "pb": StockDaily.pb,
    "market_cap": StockDaily.market_cap,
    "close": StockDaily.close,
    "turnover": StockDaily.turnover,
    "dividend_yield": StockDaily.dividend_yield,
    "roe": StockFinancial.roe,
    "revenue_yoy": StockFinancial.revenue_yoy,
    "profit_yoy": StockFinancial.profit_yoy,
    "gross_margin": StockFinancial.gross_margin,
    "debt_ratio": StockFinancial.debt_ratio,
    "industry": StockBasic.industry,
    "market": StockBasic.market,
}


def _build_clause(cond: FilterCondition):
    if cond.field not in ALLOWED_FIELDS:
        raise ValueError(f"不支持的筛选字段: {cond.field}")
    col = FIELD_MAP[cond.field]
    op, v = cond.op, cond.value
    if op == "gt":
        return col > v
    if op == "gte":
        return col >= v
    if op == "lt":
        return col < v
    if op == "lte":
        return col <= v
    if op == "eq":
        return col == v
    if op == "between":
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("between 需要长度为 2 的数组")
        return col.between(v[0], v[1])
    if op == "in":
        if not isinstance(v, list):
            raise ValueError("in 需要数组")
        return col.in_(v)
    raise ValueError(f"不支持的操作符: {op}")


def screen(db: Session, req: ScreenRequest) -> ScreenResponse:
    # 兼容 SQLite/MySQL：用 group by + max 找最新日期，再 join
    latest_daily_dates = (
        db.query(StockDaily.code, func.max(StockDaily.trade_date).label("d"))
        .group_by(StockDaily.code)
        .subquery()
    )
    latest_finan_dates = (
        db.query(StockFinancial.code, func.max(StockFinancial.report_date).label("d"))
        .group_by(StockFinancial.code)
        .subquery()
    )

    q = (
        db.query(StockBasic, StockDaily, StockFinancial)
        .outerjoin(latest_daily_dates, latest_daily_dates.c.code == StockBasic.code)
        .outerjoin(
            StockDaily,
            and_(
                StockDaily.code == latest_daily_dates.c.code,
                StockDaily.trade_date == latest_daily_dates.c.d,
            ),
        )
        .outerjoin(latest_finan_dates, latest_finan_dates.c.code == StockBasic.code)
        .outerjoin(
            StockFinancial,
            and_(
                StockFinancial.code == latest_finan_dates.c.code,
                StockFinancial.report_date == latest_finan_dates.c.d,
            ),
        )
    )

    if req.conditions:
        clauses = [_build_clause(c) for c in req.conditions]
        q = q.filter(and_(*clauses) if req.logic == "AND" else or_(*clauses))

    if req.sort_by and req.sort_by in FIELD_MAP:
        col = FIELD_MAP[req.sort_by]
        q = q.order_by(desc(col) if req.sort_desc else col)

    total = q.count()
    rows = q.limit(req.limit).all()

    items = [
        ScreenResultItem(
            code=basic.code,
            name=basic.name,
            industry=basic.industry,
            market=basic.market,
            pe=daily.pe if daily else None,
            pb=daily.pb if daily else None,
            close=daily.close if daily else None,
            market_cap=daily.market_cap if daily else None,
            dividend_yield=daily.dividend_yield if daily else None,
            roe=fin.roe if fin else None,
        )
        for basic, daily, fin in rows
    ]
    return ScreenResponse(total=total, items=items)
