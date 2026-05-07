"""AKShare 数据同步

三个入口：
- sync_basic：A 股全量基本信息（5500+ 只，秒级）
- sync_daily_em：全市场行情快照（东方财富批量，含 PE/PB/市值）—— 可能因网络受限失败
- sync_pool_xq：基于股票池逐只查询雪球（如沪深300 = 300 只 ≈ 2-3 分钟），含 PE/PB/股息率
                网络受限时用这个，对学年设计 demo 量级足够

财务相关字段（股息率/每股净资产）顺手写入 stock_financial 表。
"""
import time
from datetime import date, datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, StockDaily, StockFinancial


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
    """同步 A 股基本信息表（5500+ 只）"""
    import akshare as ak

    logger.info("拉取 A 股基本信息...")
    df = ak.stock_info_a_code_name()
    rows = [
        {
            "code": _to_code(str(r["code"])),
            "name": str(r["name"]),
            "industry": None,
            "market": None,
            "list_date": None,
            "total_share": None,
            "updated_at": datetime.utcnow(),
        }
        for _, r in df.iterrows()
    ]
    db.query(StockBasic).delete()
    db.commit()
    db.bulk_insert_mappings(StockBasic, rows)
    db.commit()
    logger.info("基本信息同步完成，共 {} 条", len(rows))
    return len(rows)


# ---------- 行情同步（方案A：东方财富批量） ----------

def sync_daily_em(db: Session, trade_date: date | None = None) -> int:
    """全市场实时快照（东方财富）。一次拉 5500+ 只，含 PE/PB/总市值。
    在部分网络下可能 RemoteDisconnected，失败时请改用 sync_pool_xq。
    """
    import akshare as ak

    logger.info("[EM] 拉取全市场实时快照...")
    df = ak.stock_zh_a_spot_em()
    today = trade_date or date.today()
    rows = []
    for _, r in df.iterrows():
        symbol = str(r.get("代码", "")).zfill(6)
        if not symbol.isdigit():
            continue
        rows.append({
            "code": _to_code(symbol),
            "trade_date": today,
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
        })
    db.query(StockDaily).filter(StockDaily.trade_date == today).delete()
    db.commit()
    db.bulk_insert_mappings(StockDaily, rows)
    db.commit()
    logger.info("[EM] 行情快照同步完成，共 {} 条", len(rows))
    return len(rows)


# ---------- 行情同步（方案 A2：新浪全市场，无 PE/PB） ----------

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
    logger.info("[INDUSTRY] 池 {}：{} 只，补行业...", pool, len(pool_list))

    if pool == "bj":
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
    updated = 0
    failed = 0
    for i, p in enumerate(pool_list, 1):
        try:
            df = ak.stock_individual_basic_info_xq(symbol=_to_xq(p["code"]))
            kv = dict(zip(df["item"], df["value"]))
            basic = db.get(StockBasic, p["code"])
            if basic is None:
                continue
            ind = kv.get("affiliate_industry") or {}
            ind_name = (ind.get("ind_name") if isinstance(ind, dict) else None) or None
            # 只在拉到值时覆盖（保留 bj 快路径已经写入的字段）
            if ind_name:
                basic.industry = ind_name
            basic.market = _market_from_code(p["code"])
            ts_share = _f(kv.get("reg_asset"), scale=1e8)
            if ts_share is not None:
                basic.total_share = ts_share
            ts = kv.get("listed_date")
            if isinstance(ts, (int, float)) and ts > 0:
                basic.list_date = datetime.fromtimestamp(ts / 1000).date()
            updated += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                logger.warning("[INDUSTRY] {} 失败: {}", p["code"], str(e)[:60])
        if i % 200 == 0:
            db.commit()
            logger.info("[INDUSTRY] 进度 {}/{}", i, len(pool_list))
        time.sleep(sleep_sec)
    db.commit()
    logger.info("[INDUSTRY] 完成：更新 {} / 失败 {}", updated, failed)
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


def sync_pool_financial(db: Session, pool: str = "csi300", sleep_sec: float = 0.15) -> int:
    """逐只拉财务摘要写入 stock_financial（最新一期）。
    覆盖 ROE / 营收同比 / 净利同比 / 毛利率 / 资产负债率 / 净利润 / 营收。
    保留同期已写入的 dividend_yield。"""
    import akshare as ak

    pool_list = fetch_pool(pool)
    logger.info("[FIN] 池 {}：{} 只，补财务...", pool, len(pool_list))

    indicators = {
        "净资产收益率(ROE)": "roe",
        "营业总收入增长率": "revenue_yoy",
        "归属母公司净利润增长率": "profit_yoy",
        "毛利率": "gross_margin",
        "资产负债率": "debt_ratio",
        "归母净利润": "net_profit",      # 元
        "营业总收入": "revenue",         # 元
    }
    updated = 0
    failed = 0
    for i, p in enumerate(pool_list, 1):
        try:
            sym = p["code"].split(".")[0]
            df = ak.stock_financial_abstract(symbol=sym)
            # 取最新一期列（除「选项/指标」外第一列）
            data_cols = [c for c in df.columns if c not in ("选项", "指标")]
            if not data_cols:
                continue
            latest_col = data_cols[0]   # 已按时间倒序
            try:
                rep_date = date(int(latest_col[:4]), int(latest_col[4:6]), int(latest_col[6:8]))
            except (ValueError, TypeError):
                continue

            # 同一指标可能在多分类中重复出现，用「常用指标」分类优先
            picked: dict[str, float | None] = {}
            for _, r in df.iterrows():
                ind, dest = r["指标"], indicators.get(r["指标"])
                if dest and (dest not in picked or r["选项"] == "常用指标"):
                    picked[dest] = _f(r[latest_col])

            row = db.query(StockFinancial).filter(
                StockFinancial.code == p["code"],
                StockFinancial.report_date == rep_date,
            ).first()
            if row is None:
                row = StockFinancial(code=p["code"], report_date=rep_date)
                db.add(row)
            # akshare 给的 ROE / 毛利率 / 资产负债率 都是 YTD 累计口径；
            # ROE 折算到年化便于跨季度横向对比（Q1 ×4 / Q2 ×2 / Q3 ×4/3 / Q4 ×1）
            if picked.get("roe") is not None:
                m = rep_date.month
                factor = {3: 4.0, 6: 2.0, 9: 4 / 3, 12: 1.0}.get(m, 1.0)
                picked["roe"] = picked["roe"] * factor

            for k, v in picked.items():
                if k in {"net_profit", "revenue"} and v is not None:
                    v = v / 1e8  # 元 → 亿元
                setattr(row, k, v)
            updated += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                logger.warning("[FIN] {} 失败: {}", p["code"], str(e)[:60])
        if i % 50 == 0:
            db.commit()
            logger.info("[FIN] 进度 {}/{}", i, len(pool_list))
        time.sleep(sleep_sec)
    db.commit()
    logger.info("[FIN] 完成：更新 {} / 失败 {}", updated, failed)
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
    logger.info("[XQ] 股票池 {}：{} 只，开始逐只拉取...", pool, len(pool_list))

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
    failed = 0

    for i, p in enumerate(pool_list, 1):
        try:
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
        except Exception as e:
            failed += 1
            if failed <= 5:
                logger.warning("[XQ] {} 拉取失败: {}", p["code"], str(e)[:60])

        if i % 50 == 0:
            logger.info("[XQ] 进度 {}/{}", i, len(pool_list))
        time.sleep(sleep_sec)

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

    logger.info("[XQ] 完成：新增 {} / 更新 {} / 失败 {}", inserted, updated, failed)
    return inserted + updated
