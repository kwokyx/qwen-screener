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
            trade_date=daily.trade_date if daily else None,
            pe=daily.pe if daily else None,
            pb=daily.pb if daily else None,
            close=daily.close if daily else None,
            market_cap=daily.market_cap if daily else None,
            dividend_yield=daily.dividend_yield if daily else None,
            turnover=daily.turnover if daily else None,
            roe=fin.roe if fin else None,
            revenue_yoy=fin.revenue_yoy if fin else None,
            profit_yoy=fin.profit_yoy if fin else None,
            gross_margin=fin.gross_margin if fin else None,
            debt_ratio=fin.debt_ratio if fin else None,
        )
        for basic, daily, fin in rows
    ]
    return ScreenResponse(total=total, items=items)
