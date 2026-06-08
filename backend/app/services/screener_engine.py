"""传统多条件筛选引擎

将 FilterCondition 列表翻译成 SQLAlchemy 查询。这一层不依赖千问，
是系统的"基础筛选模块"，论文里独立成章。
"""
from sqlalchemy import and_, case, desc, func, or_
from sqlalchemy.orm import Session, aliased

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
SORT_FIELDS = {*FIELD_MAP, "change_pct", "score"}
STRING_FIELDS = {"industry", "market"}


def validate_screen_request(req: ScreenRequest) -> None:
    """Reject malformed tool arguments before building or executing SQL."""
    if req.sort_by is not None and req.sort_by not in SORT_FIELDS:
        raise ValueError(f"不支持的排序字段: {req.sort_by}")
    for cond in req.conditions:
        if cond.field in STRING_FIELDS:
            if cond.op == "eq" and isinstance(cond.value, str) and cond.value:
                continue
            if cond.op == "in" and isinstance(cond.value, list) and cond.value and all(
                isinstance(item, str) and item for item in cond.value
            ):
                continue
            raise ValueError(f"{cond.field} 仅支持非空字符串 eq 或非空字符串数组 in")
        if cond.op == "between":
            if isinstance(cond.value, list) and len(cond.value) == 2 and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in cond.value
            ):
                continue
            raise ValueError("between 需要两个数字")
        if cond.op == "in":
            if isinstance(cond.value, list) and cond.value and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in cond.value
            ):
                continue
            raise ValueError("数值字段的 in 需要非空数字数组")
        if not isinstance(cond.value, (int, float)) or isinstance(cond.value, bool):
            raise ValueError(f"{cond.field} 需要数字阈值")


def _build_clause(cond: FilterCondition):
    if cond.field not in ALLOWED_FIELDS:
        raise ValueError(f"不支持的筛选字段: {cond.field}")
    col = FIELD_MAP[cond.field]
    op, v = cond.op, cond.value

    # industry 字段对千问输出的"宽口径行业名"做模糊匹配
    # 例如千问说 "家电"，DB 里只有 "白色家电"/"小家电"/"黑色家电"/"厨卫电器"
    # → 用 LIKE '%家电%' 命中前三；并附加同义词扩展（家电 → 家居用品等不需）
    if cond.field == "industry":
        terms = []
        if op == "in" and isinstance(v, list):
            terms = [str(x) for x in v if x]
        elif op == "eq" and v is not None:
            terms = [str(v)]
        else:
            # 其他操作符（gt/lt 等）对字符串无意义，回退到原行为
            return _basic_clause(col, op, v)
        # 同义词 / 简称扩展：用户/千问 常用词 → DB 里的具体行业字符串集合
        SYN = {
            "食品饮料": ["食品", "饮料"],
            "消费":     ["白酒", "食品", "饮料", "美容", "纺织", "服装", "家电", "家居", "零售", "旅游", "酒店", "影视", "游戏", "教育", "医疗服务"],
            "大消费":   ["白酒", "食品", "饮料", "美容", "纺织", "服装", "家电", "家居", "零售", "旅游", "酒店"],
            "家电":     ["家电", "厨卫电器"],
            "纺织服饰": ["纺织", "服装"],
            "纺服":     ["纺织", "服装"],
            "服装":     ["服装"],
            "商贸零售": ["零售", "贸易", "医药商业"],
            "零售":     ["零售"],
            "社会服务": ["社会服务", "旅游", "酒店", "教育"],
            "旅游":     ["旅游", "酒店"],
            "金融":     ["银行", "证券", "保险", "多元金融"],
            "周期":     ["钢铁", "煤炭", "有色", "化工", "石油"],
            "新能源":   ["电池", "光伏", "风电", "新能源"],
            "新能源车": ["汽车", "电池"],
            "汽车":     ["汽车"],
            "半导体":   ["半导体"],
            "医药":     ["制药", "中药", "生物制品", "医疗", "医药"],
            "TMT":      ["半导体", "软件", "通信", "传媒", "游戏", "IT", "消费电子", "光学"],
            "科技":     ["半导体", "软件", "通信", "光学", "消费电子", "IT"],
            "AI":       ["半导体", "软件", "IT", "通信", "消费电子"],
            "军工":     ["军工"],
        }
        # 把每个 term 拆出关键字 patterns
        patterns: list[str] = []
        for t in terms:
            if t in SYN:
                patterns.extend(SYN[t])
            else:
                patterns.append(t)
        # 去重
        seen, dedup = set(), []
        for p in patterns:
            if p not in seen:
                seen.add(p); dedup.append(p)
        # 拼 OR(LIKE)
        clauses = [col.like(f"%{p}%") for p in dedup]
        if not clauses:
            return col.is_(None)  # 不会命中
        if len(clauses) == 1:
            return clauses[0]
        return or_(*clauses)

    return _basic_clause(col, op, v)


def _basic_clause(col, op, v):
    if op == "gt":   return col > v
    if op == "gte":  return col >= v
    if op == "lt":   return col < v
    if op == "lte":  return col <= v
    if op == "eq":   return col == v
    if op == "between":
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("between 需要长度为 2 的数组")
        return col.between(v[0], v[1])
    if op == "in":
        if not isinstance(v, list):
            raise ValueError("in 需要数组")
        return col.in_(v)
    raise ValueError(f"不支持的操作符: {op}")


def _quality_score_expr(change_pct):
    """Composite score used by results page sorting.

    It is intentionally simple and explainable: quality (ROE), shareholder
    return (dividend yield), valuation (PE/PB), scale and short-term momentum.
    The expression runs in SQL so pagination stays globally sorted.
    """
    roe_score = case(
        (StockFinancial.roe.is_(None), 0.0),
        (StockFinancial.roe < 0, 0.0),
        (StockFinancial.roe > 30, 36.0),
        else_=StockFinancial.roe * 1.2,
    )
    dividend_score = case(
        (StockDaily.dividend_yield.is_(None), 0.0),
        (StockDaily.dividend_yield < 0, 0.0),
        (StockDaily.dividend_yield > 8, 17.6),
        else_=StockDaily.dividend_yield * 2.2,
    )
    pe_score = case(
        (StockDaily.pe.is_(None), 0.0),
        (StockDaily.pe <= 0, 0.0),
        (StockDaily.pe <= 10, 20.0),
        (StockDaily.pe <= 20, 16.0),
        (StockDaily.pe <= 35, 10.0),
        (StockDaily.pe <= 60, 5.0),
        else_=1.0,
    )
    pb_score = case(
        (StockDaily.pb.is_(None), 0.0),
        (StockDaily.pb <= 0, 0.0),
        (StockDaily.pb <= 1.5, 12.0),
        (StockDaily.pb <= 3, 8.0),
        (StockDaily.pb <= 5, 4.0),
        else_=1.0,
    )
    scale_score = case(
        (StockDaily.market_cap.is_(None), 0.0),
        (StockDaily.market_cap >= 1000, 10.0),
        (StockDaily.market_cap >= 300, 7.0),
        (StockDaily.market_cap >= 100, 5.0),
        else_=2.0,
    )
    momentum_score = case(
        (change_pct.is_(None), 0.0),
        (change_pct < -8, 0.0),
        (change_pct < 0, 2.0),
        (change_pct < 3, 5.0),
        (change_pct < 8, 7.0),
        else_=4.0,
    )
    raw_score = roe_score + dividend_score + pe_score + pb_score + scale_score + momentum_score
    return case((raw_score > 99, 99.0), else_=raw_score).label("score")


def _bounded(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 0.0
    return min(max(value, low), high)


def _quality_score(daily: StockDaily | None, previous: StockDaily | None, fin: StockFinancial | None) -> float | None:
    if not daily and not fin:
        return None
    change_pct = _change_pct(daily.close if daily else None, previous.close if previous else None)
    pe = daily.pe if daily else None
    pb = daily.pb if daily else None
    roe = fin.roe if fin else None
    dividend_yield = daily.dividend_yield if daily else None
    market_cap = daily.market_cap if (daily and daily.market_cap is not None) else None
    if market_cap is None and daily and daily.close and basic and basic.total_share:
        market_cap = daily.close * basic.total_share

    pe_score = 0.0
    if pe is not None and pe > 0:
        if pe <= 10:
            pe_score = 20.0
        elif pe <= 20:
            pe_score = 16.0
        elif pe <= 35:
            pe_score = 10.0
        elif pe <= 60:
            pe_score = 5.0
        else:
            pe_score = 1.0

    pb_score = 0.0
    if pb is not None and pb > 0:
        if pb <= 1.5:
            pb_score = 12.0
        elif pb <= 3:
            pb_score = 8.0
        elif pb <= 5:
            pb_score = 4.0
        else:
            pb_score = 1.0

    scale_score = 0.0
    if market_cap is not None:
        if market_cap >= 1000:
            scale_score = 10.0
        elif market_cap >= 300:
            scale_score = 7.0
        elif market_cap >= 100:
            scale_score = 5.0
        else:
            scale_score = 2.0

    momentum_score = 0.0
    if change_pct is not None:
        if change_pct < -8:
            momentum_score = 0.0
        elif change_pct < 0:
            momentum_score = 2.0
        elif change_pct < 3:
            momentum_score = 5.0
        elif change_pct < 8:
            momentum_score = 7.0
        else:
            momentum_score = 4.0

    score = (
        _bounded(roe, 0, 30) * 1.2
        + _bounded(dividend_yield, 0, 8) * 2.2
        + pe_score
        + pb_score
        + scale_score
        + momentum_score
    )
    return round(min(score, 99.0), 1)


def _covered_market_date(db: Session, basic_count: int, before=None):
    """Return the latest market-wide date instead of a sparse backfilled date."""
    if not basic_count:
        return None
    min_rows = max(100, int(basic_count * 0.5))

    latest_date_query = db.query(func.max(StockDaily.trade_date))
    if before is not None:
        latest_date_query = latest_date_query.filter(StockDaily.trade_date < before)
    latest_date = latest_date_query.scalar()
    if latest_date:
        count_query = db.query(func.count(StockDaily.id)).filter(StockDaily.trade_date == latest_date)
        if count_query.scalar() >= min_rows:
            return latest_date

    grouped_query = db.query(StockDaily.trade_date, func.count(StockDaily.id).label("n"))
    if before is not None:
        grouped_query = grouped_query.filter(StockDaily.trade_date < before)
    row = (
        grouped_query
        .group_by(StockDaily.trade_date)
        .having(func.count(StockDaily.id) >= min_rows)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    return row[0] if row else None


def screen(db: Session, req: ScreenRequest) -> ScreenResponse:
    validate_screen_request(req)
    previous_daily = aliased(StockDaily)
    latest_finan_dates = (
        db.query(StockFinancial.code, func.max(StockFinancial.report_date).label("d"))
        .group_by(StockFinancial.code)
        .subquery()
    )
    basic_count = db.query(func.count(StockBasic.code)).scalar() or 0
    latest_market_date = _covered_market_date(db, basic_count)
    previous_market_date = None
    if latest_market_date:
        previous_market_date = _covered_market_date(db, basic_count, before=latest_market_date)

    if latest_market_date:
        q = (
            db.query(StockBasic, StockDaily, previous_daily, StockFinancial)
            .outerjoin(
                StockDaily,
                and_(
                    StockDaily.code == StockBasic.code,
                    StockDaily.trade_date == latest_market_date,
                ),
            )
            .outerjoin(
                previous_daily,
                and_(
                    previous_daily.code == StockBasic.code,
                    previous_daily.trade_date == previous_market_date,
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
    else:
        # 回退路径：数据日期稀疏时按每只股票自己的最新记录取值。
        latest_daily_dates = (
            db.query(StockDaily.code, func.max(StockDaily.trade_date).label("d"))
            .group_by(StockDaily.code)
            .subquery()
        )
        previous_daily_dates = (
            db.query(StockDaily.code, func.max(StockDaily.trade_date).label("d"))
            .join(latest_daily_dates, latest_daily_dates.c.code == StockDaily.code)
            .filter(StockDaily.trade_date < latest_daily_dates.c.d)
            .group_by(StockDaily.code)
            .subquery()
        )
        q = (
            db.query(StockBasic, StockDaily, previous_daily, StockFinancial)
            .outerjoin(latest_daily_dates, latest_daily_dates.c.code == StockBasic.code)
            .outerjoin(
                StockDaily,
                and_(
                    StockDaily.code == latest_daily_dates.c.code,
                    StockDaily.trade_date == latest_daily_dates.c.d,
                ),
            )
            .outerjoin(previous_daily_dates, previous_daily_dates.c.code == StockBasic.code)
            .outerjoin(
                previous_daily,
                and_(
                    previous_daily.code == previous_daily_dates.c.code,
                    previous_daily.trade_date == previous_daily_dates.c.d,
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

    change_pct = (
        (StockDaily.close - previous_daily.close)
        / func.nullif(previous_daily.close, 0)
        * 100
    )
    quality_score = _quality_score_expr(change_pct)
    sort_fields = {**FIELD_MAP, "change_pct": change_pct, "score": quality_score}
    if req.sort_by:
        col = sort_fields[req.sort_by]
        q = q.order_by(
            col.is_(None).asc(),
            desc(col) if req.sort_desc else col.asc(),
            StockBasic.code.asc(),
        )
    else:
        q = q.order_by(StockBasic.code.asc())

    total = basic_count if not req.conditions else q.order_by(None).count()
    rows = q.offset(req.offset).limit(req.limit).all()

    items = [
        ScreenResultItem(
            code=basic.code,
            name=basic.name,
            industry=basic.industry,
            market=basic.market,
            trade_date=daily.trade_date if daily else None,
            pe=daily.pe if daily else None,
            pb=daily.pb if daily else None,
            close=daily.close if daily else None,
            market_cap=daily.market_cap if (daily and daily.market_cap is not None) else (
                round(daily.close * basic.total_share, 2) if (daily and daily.close and basic.total_share) else None
            ),
            dividend_yield=daily.dividend_yield if daily else None,
            turnover=daily.turnover if daily else None,
            score=_quality_score(daily, previous, fin),
            prev_close=previous.close if previous else None,
            change_pct=_change_pct(daily.close if daily else None, previous.close if previous else None),
            roe=fin.roe if fin else None,
            revenue_yoy=fin.revenue_yoy if fin else None,
            profit_yoy=fin.profit_yoy if fin else None,
            gross_margin=fin.gross_margin if fin else None,
            debt_ratio=fin.debt_ratio if fin else None,
        )
        for basic, daily, previous, fin in rows
    ]
    trade_date = latest_market_date or db.query(func.max(StockDaily.trade_date)).scalar()
    return ScreenResponse(
        total=total,
        items=items,
        offset=req.offset,
        limit=req.limit,
        trade_date=trade_date,
    )


def _change_pct(close: float | None, previous_close: float | None) -> float | None:
    if close is None or previous_close in (None, 0):
        return None
    return (close - previous_close) / previous_close * 100
