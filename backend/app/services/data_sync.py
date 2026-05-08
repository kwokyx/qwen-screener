"""AKShare 数据同步

主要入口（被 scheduler 调度，写 stock_basic / stock_daily / stock_financial）：
- sync_basic：A 股代码 + 名字（akshare stock_info_a_code_name，秒级）
- sync_daily_sina：全市场 OHLC 快照（新浪 5500+ 一次拉完，无 PE）
- sync_full_valuation_em：全市场 PE/PB/市值/换手率（东财一次调用）
- sync_pool_xq：股票池逐只调雪球（300/500 只，~2-3 分钟），追加 TTM-PE + 股息率
- sync_pool_industry / sync_pool_financial：池内逐只补行业 / 财务字段
- 全部使用 upsert 模式，不 delete-then-insert，避免半路失败清空已有数据
"""
import time
from datetime import date, datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, StockDaily, StockFinancial


# ---------- akshare 全局超时补丁 ----------
# akshare 内部用 requests.Session.send，默认无 timeout，单只股票卡住会拖死整个 sync。
# 这里给所有 requests 强制兜底 15s（不覆盖调用方主动设置的更大值）。
def _install_requests_timeout(default_timeout: float = 15.0):
    import requests
    _orig_send = requests.Session.send
    if getattr(_orig_send, "_timeout_patched", False):
        return
    def send(self, request, **kwargs):
        kwargs.setdefault("timeout", default_timeout)
        return _orig_send(self, request, **kwargs)
    send._timeout_patched = True
    requests.Session.send = send

_install_requests_timeout()


# ---------- 通用工具 ----------

def _to_code(symbol: str) -> str:
    """600000 → 600000.SH; 000001 → 000001.SZ; 4/8 开头 → BJ"""
    if symbol.startswith(("60", "68", "11", "13")):
        return f"{symbol}.SH"
    if symbol.startswith(("00", "30", "12")):
        return f"{symbol}.SZ"
    return f"{symbol}.BJ"


def _to_xq(code: str) -> str:
    """600000.SH → SH600000；用于雪球接口入参"""
    sym, mkt = code.split(".")
    return f"{mkt}{sym}"


def process_pool(
    pool_list: list[dict],
    process_fn,
    *,
    label: str,
    sleep_sec: float = 0.1,
    log_every: int = 200,
    on_progress=None,
) -> tuple[int, int]:
    """三个 sync 函数共用的迭代器：try/except + 进度 log + sleep。

    process_fn(item) 是单只股票的业务逻辑。返回 truthy 计为成功。
    on_progress(i) 在每个 log_every 边界被调用（用于阶段性 db.commit()）。
    抛异常视为失败但不中断；最多打印前 5 次失败，避免日志炸。
    """
    n = len(pool_list)
    logger.info("[{}]：{} 只，开始处理", label, n)
    success, failed = 0, 0
    for i, p in enumerate(pool_list, 1):
        try:
            ok = process_fn(p)
            if ok is not False:  # None / True 都算成功
                success += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                logger.warning("[{}] {} 失败: {}", label, p.get("code", "?"), str(e)[:60])
        if i % log_every == 0:
            logger.info("[{}] 进度 {}/{}", label, i, n)
            if on_progress is not None:
                try:
                    on_progress(i)
                except Exception:
                    pass
        time.sleep(sleep_sec)
    logger.info("[{}] 完成：成功 {} / 失败 {}", label, success, failed)
    return success, failed


def _f(v, scale: float = 1.0) -> float | None:
    try:
        if v is None or v == "" or v == "-":
            return None
        import pandas as pd
        if pd.isna(v):
            return None
        return float(v) / scale
    except (ValueError, TypeError):
        return None


# ---------- 基本信息 ----------

def sync_basic(db: Session) -> int:
    """同步 A 股基本信息表（5500+ 只）。upsert：保留已写入的 industry / list_date 等字段。"""
    import akshare as ak

    logger.info("拉取 A 股基本信息...")
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        logger.warning("akshare 返回空，跳过 basic 同步避免清空已有数据")
        return 0

    existing = {b.code: b for b in db.query(StockBasic).all()}
    inserted = 0
    updated = 0
    for _, r in df.iterrows():
        code = _to_code(str(r["code"]))
        name = str(r["name"])
        b = existing.get(code)
        if b:
            if b.name != name:
                b.name = name
            b.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(StockBasic(
                code=code, name=name,
                industry=None, market=None, list_date=None, total_share=None,
                updated_at=datetime.utcnow(),
            ))
            inserted += 1
    db.commit()
    logger.info("基本信息同步完成：新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


# ---------- 行情同步：新浪全市场（OHLC，无 PE） ----------

def sync_daily_sina(db: Session, trade_date: date | None = None) -> int:
    """新浪源全市场行情快照，5500+ 只一次拉完。
    缺 PE/PB/总市值/换手率/股息率，只覆盖 OHLC + volume + amount。
    适合在东方财富不可达时打底——保证行情类查询（涨跌榜/板块涨跌）覆盖全市场。
    """
    import akshare as ak

    logger.info("[SINA] 拉取全市场实时快照（无 PE/市值）...")
    df = ak.stock_zh_a_spot()
    today = trade_date or date.today()
    rows = []
    for _, r in df.iterrows():
        raw = str(r.get("代码", "")).strip().lower()
        # 新浪格式：sh600000 / sz000001 / bj920000
        if raw.startswith("sh"):
            code = raw[2:] + ".SH"
        elif raw.startswith("sz"):
            code = raw[2:] + ".SZ"
        elif raw.startswith("bj"):
            code = raw[2:] + ".BJ"
        else:
            # 已是数字或不识别
            sym = ''.join(c for c in raw if c.isdigit())
            if not sym:
                continue
            code = _to_code(sym.zfill(6))
        rows.append({
            "code": code,
            "trade_date": today,
            "open": _f(r.get("今开")),
            "high": _f(r.get("最高")),
            "low": _f(r.get("最低")),
            "close": _f(r.get("最新价")),
            "volume": _f(r.get("成交量")),
            "amount": _f(r.get("成交额")),
            # PE/PB/市值/换手率/股息率 没有 —— 让 csi500 同步过的那 800 只继续保留 NULL
        })
    if not rows:
        logger.warning("[SINA] 拉到 0 行，跳过")
        return 0
    # 关键：先删掉今天的行（如果之前 csi300/500 同步过有部分数据）再 insert
    # 但要保留 csi500 同步进来的 PE/PB 等字段——所以改成 upsert 模式
    existing = {
        d.code: d for d in db.query(StockDaily).filter(StockDaily.trade_date == today).all()
    }
    inserted = 0
    updated = 0
    for r in rows:
        d = existing.get(r["code"])
        if d:
            # 仅覆盖 OHLC/volume/amount，保留已有 PE/PB/市值/换手率
            for k in ("open", "high", "low", "close", "volume", "amount"):
                if r[k] is not None:
                    setattr(d, k, r[k])
            updated += 1
        else:
            db.add(StockDaily(**r))
            inserted += 1
    db.commit()
    logger.info("[SINA] 完成：新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


# ---------- 行情同步（方案B：股票池 + 雪球逐只） ----------

POOL_PRESETS = {
    "csi300": "000300",   # 沪深300
    "csi500": "000905",   # 中证500
    "sse50": "000016",    # 上证50
}


def fetch_pool(pool: str = "csi300") -> list[dict]:
    """获取股票池成分列表，返回 [{code, name}, ...]
    支持：csi300/csi500/sse50（指数）、bj（北交所全量）、all（全 A 股 5500+ 只）。
    """
    import akshare as ak

    if pool == "all":
        df = ak.stock_info_a_code_name()
        return [
            {
                "code": _to_code(str(r["code"]).zfill(6)),
                "name": str(r["name"]),
            }
            for _, r in df.iterrows()
        ]

    if pool == "bj":
        df = ak.stock_info_bj_name_code()
        return [
            {
                "code": str(r["证券代码"]) + ".BJ",
                "name": str(r["证券简称"]),
                # 北交所列表里直接带行业 / 上市日期 / 总股本，省去逐只查雪球
                "_industry": str(r.get("所属行业") or "") or None,
                "_list_date": r.get("上市日期"),
                "_total_share": _f(r.get("总股本"), scale=1e8),
            }
            for _, r in df.iterrows()
        ]

    if pool not in POOL_PRESETS:
        raise ValueError(f"未知股票池: {pool}，支持 {list(POOL_PRESETS) + ['bj', 'all']}")

    df = ak.index_stock_cons_csindex(symbol=POOL_PRESETS[pool])
    return [
        {
            "code": _to_code(str(r["成分券代码"]).zfill(6)),
            "name": str(r["成分券名称"]),
        }
        for _, r in df.iterrows()
    ]


def sync_pool_industry(db: Session, pool: str = "csi300", sleep_sec: float = 0.1) -> int:
    """补 stock_basic 的 industry / 上市时间 / 总股本。
    - 指数池（csi300/csi500/sse50）：逐只调雪球 individual_basic_info
    - bj 池：股票列表本身就带行业/上市日期/总股本，直接用，不需要逐只远程调用
    """
    pool_list = fetch_pool(pool)

    if pool == "bj":
        logger.info("[INDUSTRY bj] {} 只走快路径（列表自带行业/上市日期）", len(pool_list))
        # 快路径：列表已带行业/上市日期/总股本，无需 312 次雪球调用
        updated = 0
        for p in pool_list:
            basic = db.get(StockBasic, p["code"])
            if basic is None:
                continue
            basic.industry = p.get("_industry")
            basic.market = "北交所"
            basic.total_share = p.get("_total_share")
            ld = p.get("_list_date")
            if isinstance(ld, date):
                basic.list_date = ld
            updated += 1
        db.commit()
        logger.info("[INDUSTRY] bj 完成：更新 {}", updated)
        return updated

    import akshare as ak

    def process(p):
        df = ak.stock_individual_basic_info_xq(symbol=_to_xq(p["code"]))
        kv = dict(zip(df["item"], df["value"]))
        basic = db.get(StockBasic, p["code"])
        if basic is None:
            return False
        ind = kv.get("affiliate_industry") or {}
        ind_name = (ind.get("ind_name") if isinstance(ind, dict) else None) or None
        if ind_name:  # 只在拉到值时覆盖，保留 bj 快路径写好的字段
            basic.industry = ind_name
        basic.market = _market_from_code(p["code"])
        ts_share = _f(kv.get("reg_asset"), scale=1e8)
        if ts_share is not None:
            basic.total_share = ts_share
        ts = kv.get("listed_date")
        if isinstance(ts, (int, float)) and ts > 0:
            basic.list_date = datetime.fromtimestamp(ts / 1000).date()

    updated, _ = process_pool(
        pool_list, process,
        label=f"INDUSTRY {pool}", sleep_sec=sleep_sec,
        on_progress=lambda i: db.commit(),
    )
    db.commit()
    return updated


def _market_from_code(code: str) -> str:
    sym, mkt = code.split(".")
    if mkt == "BJ":
        return "北交所"
    if sym.startswith(("688", "689")):
        return "科创板"
    if sym.startswith("300") or sym.startswith("301"):
        return "创业板"
    return "主板"


_FIN_INDICATORS = {
    "净资产收益率(ROE)":      "roe",
    "营业总收入增长率":        "revenue_yoy",
    "归属母公司净利润增长率":   "profit_yoy",
    "毛利率":                "gross_margin",
    "资产负债率":             "debt_ratio",
    "归母净利润":             "net_profit",   # 元，下面折算到亿
    "营业总收入":             "revenue",      # 元，下面折算到亿
}


def sync_pool_financial(db: Session, pool: str = "csi300", sleep_sec: float = 0.15) -> int:
    """逐只拉财务摘要写入 stock_financial（最新一期）。
    覆盖 ROE / 营收同比 / 净利同比 / 毛利率 / 资产负债率 / 净利润 / 营收。
    """
    import akshare as ak
    pool_list = fetch_pool(pool)

    def process(p):
        sym = p["code"].split(".")[0]
        df = ak.stock_financial_abstract(symbol=sym)
        data_cols = [c for c in df.columns if c not in ("选项", "指标")]
        if not data_cols:
            return False
        latest_col = data_cols[0]   # 已按时间倒序
        try:
            rep_date = date(int(latest_col[:4]), int(latest_col[4:6]), int(latest_col[6:8]))
        except (ValueError, TypeError):
            return False

        # 同一指标可能在多分类中重复出现，用「常用指标」分类优先
        picked: dict[str, float | None] = {}
        for _, r in df.iterrows():
            dest = _FIN_INDICATORS.get(r["指标"])
            if dest and (dest not in picked or r["选项"] == "常用指标"):
                picked[dest] = _f(r[latest_col])

        row = db.query(StockFinancial).filter(
            StockFinancial.code == p["code"],
            StockFinancial.report_date == rep_date,
        ).first()
        if row is None:
            row = StockFinancial(code=p["code"], report_date=rep_date)
            db.add(row)
        # akshare 给的 ROE 是 YTD 累计口径，折算到年化便于跨季度横向对比
        if picked.get("roe") is not None:
            m = rep_date.month
            factor = {3: 4.0, 6: 2.0, 9: 4 / 3, 12: 1.0}.get(m, 1.0)
            picked["roe"] = picked["roe"] * factor
        for k, v in picked.items():
            if k in {"net_profit", "revenue"} and v is not None:
                v = v / 1e8  # 元 → 亿元
            setattr(row, k, v)

    updated, _ = process_pool(
        pool_list, process,
        label=f"FIN {pool}", sleep_sec=sleep_sec,
        on_progress=lambda i: db.commit(),
    )
    db.commit()
    return updated


def sync_full_valuation_em(db: Session, trade_date: date | None = None) -> int:
    """全市场估值（PE/PB/总市值/换手率）—— 一次东方财富 spot 调用覆盖 5500+ 只。
    雪球 spot 对小盘 / 北交所返回 None，所以这里改用东财作为主源。
    upsert 模式，不删现有行（保留 csi300/csi500 后续覆盖的 xq-TTM PE 和股息率）。
    """
    import akshare as ak

    today = trade_date or date.today()
    logger.info("[EM-VAL] 拉东方财富全市场快照（PE/PB/市值/换手率）...")
    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        logger.warning("[EM-VAL] 拉到 0 行，跳过")
        return 0

    existing = {
        d.code: d for d in db.query(StockDaily).filter(StockDaily.trade_date == today).all()
    }
    inserted = 0
    updated = 0
    for _, r in df.iterrows():
        symbol = str(r.get("代码", "")).zfill(6)
        if not symbol.isdigit() or len(symbol) != 6:
            continue
        code = _to_code(symbol)
        fields = {
            "open": _f(r.get("今开")),
            "high": _f(r.get("最高")),
            "low": _f(r.get("最低")),
            "close": _f(r.get("最新价")),
            "volume": _f(r.get("成交量")),
            "amount": _f(r.get("成交额")),
            "pe": _f(r.get("市盈率-动态")),
            "pb": _f(r.get("市净率")),
            "market_cap": _f(r.get("总市值"), scale=1e8),
            "turnover": _f(r.get("换手率")),
        }
        d = existing.get(code)
        if d:
            for k, v in fields.items():
                if v is not None:
                    setattr(d, k, v)
            updated += 1
        else:
            db.add(StockDaily(code=code, trade_date=today, **fields))
            inserted += 1
    db.commit()
    logger.info("[EM-VAL] 完成：新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


def sync_pool_xq(
    db: Session,
    pool: str = "csi300",
    trade_date: date | None = None,
    sleep_sec: float = 0.15,
) -> int:
    """基于股票池逐只调雪球同步行情 + 估值 + 股息率。
    300 只 ≈ 1 分钟。失败的股票跳过、不影响其他。
    """
    import akshare as ak

    today = trade_date or date.today()
    pool_list = fetch_pool(pool)

    # 同时把池内股票补齐到 stock_basic（如果原表没拉过全 A 股，至少能查到名字）
    existing_codes = {row[0] for row in db.query(StockBasic.code).all()}
    new_basic = [
        {"code": p["code"], "name": p["name"], "updated_at": datetime.utcnow()}
        for p in pool_list if p["code"] not in existing_codes
    ]
    if new_basic:
        db.bulk_insert_mappings(StockBasic, new_basic)
        db.commit()
        logger.info("[XQ] 顺便补 {} 只到 stock_basic", len(new_basic))

    daily_rows: list[dict] = []

    def process(p):
        df = ak.stock_individual_spot_xq(symbol=_to_xq(p["code"]))
        d = dict(zip(df["item"], df["value"]))
        daily_rows.append({
            "code": p["code"],
            "trade_date": today,
            "open": _f(d.get("今开")),
            "high": _f(d.get("最高")),
            "low": _f(d.get("最低")),
            "close": _f(d.get("现价")),
            "volume": _f(d.get("成交量")),
            "amount": _f(d.get("成交额")),
            "pe": _f(d.get("市盈率(TTM)")),
            "pb": _f(d.get("市净率")),
            "market_cap": _f(d.get("流通值"), scale=1e8),  # 元 → 亿
            "turnover": _f(d.get("周转率")),
            "dividend_yield": _f(d.get("股息率(TTM)")),
        })

    process_pool(pool_list, process, label=f"XQ {pool}", sleep_sec=sleep_sec, log_every=50)

    # upsert：不清桌子，保留 EM 全市场写入的 PE/PB；csi300/csi500 这 800 只用 xq-TTM PE + 股息率覆盖
    existing = {
        d.code: d for d in db.query(StockDaily).filter(StockDaily.trade_date == today).all()
    }
    inserted = 0
    updated = 0
    for r in daily_rows:
        d = existing.get(r["code"])
        if d:
            for k, v in r.items():
                if k in ("code", "trade_date"):
                    continue
                if v is not None:
                    setattr(d, k, v)
            updated += 1
        else:
            db.add(StockDaily(**r))
            inserted += 1
    db.commit()

    logger.info("[XQ {}] upsert 完成：新增 {} / 更新 {}", pool, inserted, updated)
    return inserted + updated
