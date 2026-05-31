"""数据同步模块。

支持两种数据源：
- AKShare (akshare) — 新浪/东方财富/雪球。保留作为 legacy fallback。
- baostock (baostock) — 免费 A 股历史数据源（默认）。

AKShare 入口（legacy）：
- sync_basic：A 股代码 + 名字（akshare stock_info_a_code_name，秒级）
- sync_daily_sina：全市场 OHLC 快照（新浪 5500+ 一次拉完，无 PE）
- sync_full_valuation_em：全市场 PE/PB/市值/换手率（东财一次调用）
- sync_pool_xq：股票池逐只调雪球，追加 TTM-PE + 股息率
- sync_pool_industry / sync_pool_financial：池内逐只补行业 / 财务

baostock 入口（默认）：
- sync_basic_bs：全 A 股代码 + 名字 + 上市日期
- sync_daily_bs：全市场 K 线（OHLCV + PE + PB + 换手率），约需 30-60 分钟
- sync_financial_bs：全市场财务指标（ROE / 营收同比 / 净利同比 / 毛利率 / 资产负债率）
- sync_kline_bs：单只股票 K 线（被 API 懒加载调用）

全部使用 upsert 模式，不 delete-then-insert，避免半路失败清空已有数据。
"""
import os
import time
from datetime import date, datetime, timedelta

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, StockDaily, StockDividend, StockFinancial


BAOSTOCK_SYNC_WORKERS = int(os.getenv("BAOSTOCK_SYNC_WORKERS", "4"))
BAOSTOCK_BATCH_TIMEOUT = float(os.getenv("BAOSTOCK_BATCH_TIMEOUT", "90"))


# ---------- akshare 全局超时补丁 ----------
# akshare 内部用 requests.Session.send，默认无 timeout，单只股票卡住会拖死整个 sync。
# 仅在 akshare 被实际使用时打补丁（baostock 不需要 requests）。
def _install_requests_timeout(default_timeout: float = 15.0):
    try:
        import requests
    except ImportError:
        return
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

def _latest_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _snapshot_trade_date(trade_date: date | None = None) -> date:
    """Spot snapshots do not trade on weekends; keep them on the last weekday."""
    return _latest_weekday(trade_date or date.today())

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

SYNC_BASIC_WIPE_GUARD_RATIO = 0.8


def sync_basic(db: Session) -> int:
    """同步 A 股基本信息表（5500+ 只）。upsert：保留已写入的 industry / list_date 等字段。

    防 wipe 保护：
    1. akshare 返空（None / empty）→ 跳过
    2. akshare 行数 < DB 当前行数 * 0.8 → 认为上游异常（部分接口偶尔只返子集），
       跳过本次更新，log warning。等下次完整快照再写。
    """
    import akshare as ak

    logger.info("拉取 A 股基本信息...")
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        logger.warning("akshare 返回空，跳过 basic 同步避免清空已有数据")
        return 0

    db_cnt = db.query(StockBasic).count()
    upstream_cnt = len(df)
    if db_cnt > 0 and upstream_cnt < db_cnt * SYNC_BASIC_WIPE_GUARD_RATIO:
        logger.warning(
            "上游返回 {} 条 < DB {} 条 * {:.0%}，认为是部分/异常快照，跳过 basic 同步",
            upstream_cnt, db_cnt, SYNC_BASIC_WIPE_GUARD_RATIO,
        )
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
    today = _snapshot_trade_date(trade_date)
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


def _normalize_exchange_industry(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "nan" or "暂无" in text:
        return None
    # 深交所返回类似 "J 金融业"，保留中文部分。
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) <= 2 and parts[0].isascii():
        return parts[1].strip() or None
    return text


def _parse_share_count(value) -> float | None:
    """Convert share count to 100M shares."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-" or text == "nan":
        return None
    try:
        return float(text) / 1e8
    except ValueError:
        return None


def sync_exchange_basic_info(db: Session) -> int:
    """Use exchange list pages to supplement listing date, market and broad industry.

    This is a stable fallback for industry coverage:
    - SZSE list includes industry and total shares.
    - BJ list includes industry and total shares.
    - SSE list includes listing date but not industry.
    Existing fine-grained industry names are preserved; broad exchange industry only fills blanks.
    """
    import akshare as ak

    rows: list[dict] = []
    try:
        sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
        for _, r in sz_df.iterrows():
            symbol = str(r.get("A股代码") or "").zfill(6)
            if not symbol.isdigit():
                continue
            rows.append({
                "code": f"{symbol}.SZ",
                "name": str(r.get("A股简称") or "").strip() or None,
                "industry": _normalize_exchange_industry(r.get("所属行业")),
                "market": str(r.get("板块") or "").strip() or _market_from_code_sym(symbol),
                "list_date": r.get("A股上市日期"),
                "total_share": _parse_share_count(r.get("A股总股本")),
            })
    except Exception as exc:
        logger.warning("[EXCHANGE-BASIC] 深交所列表失败: {}", str(exc)[:120])

    try:
        sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
        for _, r in sh_df.iterrows():
            symbol = str(r.get("证券代码") or "").zfill(6)
            if not symbol.isdigit():
                continue
            rows.append({
                "code": f"{symbol}.SH",
                "name": str(r.get("证券简称") or "").strip() or None,
                "industry": None,
                "market": _market_from_code_sym(symbol),
                "list_date": r.get("上市日期"),
                "total_share": None,
            })
    except Exception as exc:
        logger.warning("[EXCHANGE-BASIC] 上交所列表失败: {}", str(exc)[:120])

    try:
        bj_df = ak.stock_info_bj_name_code()
        for _, r in bj_df.iterrows():
            symbol = str(r.get("证券代码") or "").zfill(6)
            if not symbol.isdigit():
                continue
            rows.append({
                "code": f"{symbol}.BJ",
                "name": str(r.get("证券简称") or "").strip() or None,
                "industry": _normalize_exchange_industry(r.get("所属行业")),
                "market": "北交所",
                "list_date": r.get("上市日期"),
                "total_share": _f(r.get("总股本"), scale=1e8),
            })
    except Exception as exc:
        logger.warning("[EXCHANGE-BASIC] 北交所列表失败: {}", str(exc)[:120])

    if not rows:
        logger.warning("[EXCHANGE-BASIC] 无可写入数据")
        return 0

    existing = {b.code: b for b in db.query(StockBasic).all()}
    inserted = 0
    updated = 0
    for r in rows:
        code = r["code"]
        b = existing.get(code)
        if b is None:
            db.add(StockBasic(
                code=code,
                name=r.get("name") or code,
                industry=r.get("industry"),
                market=r.get("market"),
                list_date=r.get("list_date") if isinstance(r.get("list_date"), date) else None,
                total_share=r.get("total_share"),
                updated_at=datetime.utcnow(),
            ))
            inserted += 1
            continue

        if r.get("name") and b.name != r["name"]:
            b.name = r["name"]
        if not b.industry and r.get("industry"):
            b.industry = r["industry"]
        if r.get("market"):
            b.market = r["market"]
        if b.list_date is None and r.get("list_date"):
            if isinstance(r["list_date"], date):
                b.list_date = r["list_date"]
            else:
                try:
                    b.list_date = date.fromisoformat(str(r["list_date"])[:10])
                except Exception:
                    pass
        if r.get("total_share") is not None and r["total_share"] > 0:
            b.total_share = r["total_share"]
        b.updated_at = datetime.utcnow()
        updated += 1

    db.commit()
    logger.info("[EXCHANGE-BASIC] 新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


def _ths_cookie_headers() -> dict:
    from akshare.stock_feature import stock_board_industry_ths as ths
    import py_mini_racer

    js_code = py_mini_racer.MiniRacer()
    js_code.eval(ths._get_file_content_ths("ths.js"))
    v_code = js_code.call("v")
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Cookie": f"v={v_code}",
        "hexin-v": v_code,
        "Referer": "http://q.10jqka.com.cn/thshy/",
    }


def sync_industry_ths(db: Session, sleep_sec: float = 0.18, max_pages: int = 8) -> int:
    """Fill stock_basic.industry from TongHuaShun industry constituent pages.

    AkShare exposes industry names but this installed version does not expose a
    constituent helper, so we parse the same public HTML pages directly. The
    function is intentionally best-effort: anti-scrape pages are skipped and
    exchange-list fallback can still fill broad industry names.
    """
    import akshare as ak
    import pandas as pd
    import requests
    from io import StringIO

    boards = ak.stock_board_industry_name_ths()
    if boards is None or boards.empty:
        logger.warning("[THS-INDUSTRY] 行业列表为空")
        return 0

    code_industry: dict[str, str] = {}
    failed = 0

    for i, r in boards.iterrows():
        industry = str(r.get("name") or "").strip()
        board_code = str(r.get("code") or "").strip()
        if not industry or not board_code:
            continue
        got_for_board = 0
        for page in range(1, max_pages + 1):
            url = (
                f"https://q.10jqka.com.cn/thshy/detail/code/{board_code}/"
                f"field/199112/order/desc/page/{page}/ajax/1/"
            )
            try:
                resp = requests.get(url, headers=_ths_cookie_headers(), timeout=10)
                if resp.status_code in (401, 403) or "chameleon" in resp.text:
                    time.sleep(0.6)
                    resp = requests.get(url, headers=_ths_cookie_headers(), timeout=10)
                resp.raise_for_status()
                if "chameleon" in resp.text or "<table" not in resp.text:
                    failed += 1
                    break
                df = pd.read_html(StringIO(resp.text))[0]
            except Exception as exc:
                failed += 1
                if failed <= 5:
                    logger.warning("[THS-INDUSTRY] {} 第 {} 页失败: {}", industry, page, str(exc)[:100])
                break

            if df is None or df.empty or "代码" not in df.columns:
                break

            valid_rows = 0
            for _, item in df.iterrows():
                raw = str(item.get("代码") or "").strip()
                if not raw.isdigit():
                    continue
                code = _to_code(raw.zfill(6))
                code_industry[code] = industry
                valid_rows += 1
            got_for_board += valid_rows
            if valid_rows == 0 or len(df) < 20:
                break
            time.sleep(sleep_sec)

        if (i + 1) % 15 == 0:
            logger.info("[THS-INDUSTRY] 进度 {}/{}，已映射 {} 只", i + 1, len(boards), len(code_industry))
        if got_for_board:
            time.sleep(sleep_sec)

    if not code_industry:
        logger.warning("[THS-INDUSTRY] 未获得任何行业成分")
        return 0

    existing = {b.code: b for b in db.query(StockBasic).all()}
    updated = 0
    for code, industry in code_industry.items():
        b = existing.get(code)
        if b is None:
            continue
        if b.industry != industry:
            b.industry = industry
            b.updated_at = datetime.utcnow()
            updated += 1

    db.commit()
    logger.info("[THS-INDUSTRY] 更新 {}，映射 {}，失败页/板块 {}", updated, len(code_industry), failed)
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

    today = _snapshot_trade_date(trade_date)
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


# ---------- 行情同步：腾讯全市场估值兜底 ----------

def _to_tx_symbol(code: str) -> str | None:
    """600519.SH -> sh600519, 000001.SZ -> sz000001, 920000.BJ -> bj920000."""
    try:
        sym, mkt = code.split(".")
    except ValueError:
        return None
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt.upper())
    if not prefix:
        return None
    return f"{prefix}{sym}"


def _from_tx_symbol(symbol: str) -> str | None:
    """sh600519 -> 600519.SH."""
    symbol = symbol.strip().lower()
    if len(symbol) < 8:
        return None
    prefix = symbol[:2]
    code = symbol[2:]
    suffix = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix)
    if not suffix or not code.isdigit():
        return None
    return f"{code}.{suffix}"


def _tx_float(fields: list[str], idx: int, scale: float = 1.0) -> float | None:
    if idx >= len(fields):
        return None
    return _f(fields[idx], scale=scale)


def _parse_tx_quotes(text: str) -> list[dict]:
    """Parse Tencent qt.gtimg.cn quote payload.

    Field mapping is based on the public v_* quote format:
    - 3 current price, 5 open, 33 high, 34 low
    - 36 volume in lots, 37 amount in ten-thousand CNY
    - 38 turnover %, 39 PE, 44 total market cap (100M CNY), 46 PB
    - 72 total shares, 73 circulating shares
    """
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "=\"" not in line:
            continue
        raw_symbol = line.split("=", 1)[0].replace("v_", "", 1)
        code = _from_tx_symbol(raw_symbol)
        if not code:
            continue
        payload = line.split("=\"", 1)[1].rstrip("\";")
        fields = payload.split("~")
        close = _tx_float(fields, 3)
        if close is None:
            continue
        rows.append({
            "code": code,
            "name": fields[1] if len(fields) > 1 else None,
            "open": _tx_float(fields, 5),
            "high": _tx_float(fields, 33),
            "low": _tx_float(fields, 34),
            "close": close,
            "volume": _tx_float(fields, 36, scale=0.01),   # 手 -> 股：除以 0.01 等同 * 100
            "amount": _tx_float(fields, 37, scale=0.0001),  # 万元 -> 元：除以 0.0001 等同 * 10000
            "turnover": _tx_float(fields, 38),
            "pe": _tx_float(fields, 39),
            "market_cap": _tx_float(fields, 44),
            "pb": _tx_float(fields, 46),
            "total_share": _tx_float(fields, 72, scale=1e8),
        })
    return rows


def sync_full_valuation_tx(
    db: Session,
    trade_date: date | None = None,
    batch_size: int = 300,
) -> int:
    """腾讯 quote 接口估值兜底。

    当前环境里东方财富和 baostock 偶发/经常不可达；腾讯 quote 对全市场批量
    行情更稳定。这里补齐 stock_daily 的 PE/PB/总市值/换手率，并顺手把
    stock_basic.total_share 补上，便于后续本地推导市值。
    """
    import requests

    today = _snapshot_trade_date(trade_date)
    codes = [c for (c,) in db.query(StockBasic.code).all()]
    symbols = [s for code in codes if (s := _to_tx_symbol(code))]
    if not symbols:
        logger.warning("[TX-VAL] 无可同步代码")
        return 0

    logger.info("[TX-VAL] 拉腾讯全市场 quote：{} 只, batch_size={}", len(symbols), batch_size)
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.qq.com/",
    }

    all_rows: list[dict] = []
    failed_batches = 0
    for i in range(0, len(symbols), batch_size):
        chunk = symbols[i:i + batch_size]
        try:
            resp = session.get(
                "https://qt.gtimg.cn/q=" + ",".join(chunk),
                headers=headers,
                timeout=12,
            )
            resp.raise_for_status()
            all_rows.extend(_parse_tx_quotes(resp.text))
        except Exception as exc:
            failed_batches += 1
            if failed_batches <= 3:
                logger.warning("[TX-VAL] batch {} 失败: {}", i // batch_size + 1, str(exc)[:120])
        if i and i % (batch_size * 5) == 0:
            logger.info("[TX-VAL] 进度 {}/{}", min(i, len(symbols)), len(symbols))
        time.sleep(0.05)

    if not all_rows:
        logger.warning("[TX-VAL] 拉到 0 行")
        return 0

    existing_daily = {
        d.code: d for d in db.query(StockDaily).filter(StockDaily.trade_date == today).all()
    }
    existing_basic = {b.code: b for b in db.query(StockBasic).all()}
    inserted = 0
    updated = 0
    basic_updated = 0
    for r in all_rows:
        code = r["code"]
        fields = {
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "volume": r.get("volume"),
            "amount": r.get("amount"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "market_cap": r.get("market_cap"),
            "turnover": r.get("turnover"),
        }
        d = existing_daily.get(code)
        if d:
            for k in ("open", "high", "low", "close", "volume", "amount"):
                v = fields.get(k)
                if v is not None and getattr(d, k) is None:
                    setattr(d, k, v)
            for k in ("pe", "pb", "market_cap", "turnover"):
                v = fields.get(k)
                if v is not None:
                    setattr(d, k, v)
            updated += 1
        else:
            db.add(StockDaily(code=code, trade_date=today, **fields))
            inserted += 1

        basic = existing_basic.get(code)
        total_share = r.get("total_share")
        if basic and total_share is not None and total_share > 0:
            if basic.total_share != total_share:
                basic.total_share = total_share
                basic_updated += 1

    db.commit()
    logger.info(
        "[TX-VAL] 完成：新增 {} / 更新 {} / basic 总股本更新 {} / 失败批次 {}",
        inserted, updated, basic_updated, failed_batches,
    )
    return inserted + updated


# ---------- K 线历史回填 ----------

def _fetch_hist_em(sym: str, start, end):
    """eastmoney 源（中文列名）。被 eastmoney 限流时拒绝；触发 None。"""
    import akshare as ak
    df = ak.stock_zh_a_hist(
        symbol=sym, period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    if df is None or df.empty:
        return None
    return [
        {
            "date": str(r.get("日期")),
            "open": r.get("开盘"),
            "high": r.get("最高"),
            "low": r.get("最低"),
            "close": r.get("收盘"),
            "volume": r.get("成交量"),
            "amount": r.get("成交额"),
            "turnover": r.get("换手率"),
        }
        for _, r in df.iterrows()
    ]


def _fetch_hist_sina(code: str, start, end):
    """sina 源（英文列名 + sh/sz 前缀）。eastmoney 被封时兜底。"""
    import akshare as ak
    sym, mkt = code.split(".")
    if mkt == "BJ":
        # sina 不覆盖北交所，让调用方走 em
        return None
    sina_sym = mkt.lower() + sym  # sh600519 / sz000001
    df = ak.stock_zh_a_daily(
        symbol=sina_sym,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    if df is None or df.empty:
        return None
    return [
        {
            "date": str(r.get("date")),
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "volume": r.get("volume"),
            "amount": r.get("amount"),
            "turnover": r.get("turnover"),
        }
        for _, r in df.iterrows()
    ]


def backfill_kline_single(db: Session, code: str, days: int) -> int:
    """从 akshare 拉单只股票最近 N 个交易日的日线写入 stock_daily。已有日期 skip。

    源选择：sina 优先（eastmoney 经常被限流），失败回 eastmoney。
    被 api/stock.py 的 /kline 懒加载端点和 scheduler 的全量周任务共用。
    timeout 由 _install_requests_timeout 在模块加载时打的猴子补丁兜底（15s/请求）。
    """
    from datetime import date as _date, timedelta

    sym = code.split(".")[0]
    end = _date.today()
    # 多拉一倍天数缓冲（节假日 / 停牌）
    start = end - timedelta(days=max(days * 2, 60))

    rows = None
    # 优先 sina（在 eastmoney 限流期间能跑通全市场 60d）
    try:
        rows = _fetch_hist_sina(code, start, end)
    except Exception:
        rows = None
    # sina 没数据（北交所 / sina 抖动）或失败则回 eastmoney
    if not rows:
        try:
            rows = _fetch_hist_em(sym, start, end)
        except Exception:
            rows = None
    if not rows:
        return 0

    have_dates = {
        r[0] for r in db.query(StockDaily.trade_date).filter(StockDaily.code == code).all()
    }
    inserted = 0
    for r in rows:
        raw = r.get("date")
        try:
            td = _date.fromisoformat(raw[:10])
        except Exception:
            continue
        if td in have_dates:
            continue
        try:
            db.add(StockDaily(
                code=code, trade_date=td,
                open=_f(r.get("open")),
                high=_f(r.get("high")),
                low=_f(r.get("low")),
                close=_f(r.get("close")),
                volume=_f(r.get("volume")),
                amount=_f(r.get("amount")),
                turnover=_f(r.get("turnover")),
            ))
            inserted += 1
        except Exception:
            db.rollback()
            continue
    if inserted:
        db.commit()
    return inserted


def backfill_kline_all(db: Session, days: int = 60, workers: int = 6) -> int:
    """全市场 K 线回填：给所有 stock_basic 里的代码补 N 个交易日历史。

    每个 akshare 调用本身 ~8s（sina）/ 5s（em），串行 5500 只要 12+ 小时太慢。
    瓶颈是网络，所以用 ThreadPoolExecutor 并发 (workers=6 默认)：
    - 6 个线程同时跑 akshare HTTP（彼此独立 db session）
    - SQLite 单写锁会让 db.commit() 之间排队，但 commit 本身 ~ms 级，不构成瓶颈
    - 5500 只 / 6 并发 ≈ 15-20 分钟（理想情况）
    """
    import concurrent.futures
    from app.database import SessionLocal

    codes = [c for (c,) in db.query(StockBasic.code).all()]
    n = len(codes)
    logger.info("[KLINE-BACKFILL {}d] {} 只, workers={}", days, n, workers)
    total_inserted = 0
    completed = 0
    failed = 0

    def _one(code: str) -> int:
        # 线程私有 session，避免跨线程复用同一个 Session 对象
        s = SessionLocal()
        try:
            return backfill_kline_single(s, code, days)
        except Exception as e:
            if failed <= 5:
                logger.warning("[KLINE-BACKFILL] {} 失败: {}", code, str(e)[:80])
            return 0
        finally:
            s.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for n_ins in ex.map(_one, codes):
            completed += 1
            if n_ins:
                total_inserted += n_ins
            else:
                failed += 1
            if completed % 200 == 0:
                logger.info("[KLINE-BACKFILL] 进度 {}/{}, 已写入 {} 行, 失败 {}",
                            completed, n, total_inserted, failed)

    logger.info("[KLINE-BACKFILL] 完成：{} 只处理，写入 {} 行，失败 {}",
                completed, total_inserted, failed)
    return total_inserted


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

    today = _snapshot_trade_date(trade_date)
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


# ═══════════════════════════════════════════════════════════════
#  baostock 数据同步 (默认数据源)
# ═══════════════════════════════════════════════════════════════

from app.services.providers.baostock_provider import (
    bs_session,
    bs_to_code,
    code_to_bs,
    fetch_stock_basic,
    fetch_kline,
    fetch_kline_unsafe,
    fetch_financial,
    fetch_financial_batch,
    fetch_dividend_batch,
    _ensure_login,
    _ensure_logout,
)


def _code_from_bs(bs_code: str) -> str:
    """sh.600519 → 600519.SH (alias for bs_to_code)"""
    return bs_to_code(bs_code)


def _market_from_code_sym(sym: str) -> str:
    """根据代码前缀推导板块"""
    if sym.startswith(("688", "689")):
        return "科创板"
    if sym.startswith("300") or sym.startswith("301"):
        return "创业板"
    if len(sym) >= 4 and sym[:3] in ("8", "4"):
        return "北交所"
    if sym.startswith(("60", "11", "13")):
        return "主板"
    if sym.startswith(("00", "30", "12")):
        return "主板"
    return "主板"


def sync_basic_bs(db: Session) -> int:
    """baostock 拉全量 A 股基础信息写入 stock_basic。
    upsert 模式：保留已有 industry / market 字段。
    """
    rows = fetch_stock_basic()
    if not rows:
        logger.warning("[BS-BASIC] 返回 0 条，跳过")
        return 0

    existing = {b.code: b for b in db.query(StockBasic).all()}
    inserted = 0
    updated = 0
    for r in rows:
        code = r["code"]
        sym = code.split(".")[0]
        b = existing.get(code)
        if b:
            if b.name != r["name"]:
                b.name = r["name"]
            if r.get("list_date") and b.list_date is None:
                b.list_date = r["list_date"]
            b.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(StockBasic(
                code=code,
                name=r["name"],
                industry=None,
                market=_market_from_code_sym(sym),
                list_date=r.get("list_date"),
                total_share=None,
                updated_at=datetime.utcnow(),
            ))
            inserted += 1
    db.commit()
    logger.info("[BS-BASIC] 新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


def _fetch_kline_chunk_worker(args: tuple[list[str], str | None, str | None]) -> dict:
    """Worker used by baostock full-market sync.

    This mirrors Sequoia-X's data engine: split the code list, let each process
    keep one baostock login for its chunk, then return plain rows to the parent
    process. The parent is the only process that writes SQLite, so we avoid
    cross-process SQLAlchemy sessions and SQLite write locks.
    """
    codes, start_date, end_date = args
    try:
        from app.services.providers.baostock_provider import fetch_kline_batch

        by_code = fetch_kline_batch(codes, start_date, end_date)
        rows: list[dict] = []
        for items in by_code.values():
            rows.extend(items)
        return {
            "rows": rows,
            "handled": len(codes),
            "failed": len(codes) - len(by_code),
            "error": None,
        }
    except Exception as exc:
        return {
            "rows": [],
            "handled": len(codes),
            "failed": len(codes),
            "error": str(exc)[:160],
        }


def _upsert_daily_rows(db: Session, rows: list[dict]) -> tuple[int, int]:
    """Upsert baostock K-line rows into stock_daily."""
    if not rows:
        return 0, 0

    # Keep only usable rows and dedupe the same code/date within this sync run.
    deduped: dict[tuple[str, date], dict] = {}
    for r in rows:
        code = r.get("code")
        trade_date = r.get("trade_date")
        if not code or not trade_date or r.get("close") is None:
            continue
        volume = r.get("volume")
        if volume is not None and volume <= 0:
            continue
        deduped[(code, trade_date)] = r
    if not deduped:
        return 0, 0

    dates = sorted({trade_date for _, trade_date in deduped})
    existing_rows = (
        db.query(StockDaily)
        .filter(StockDaily.trade_date.in_(dates))
        .all()
    )
    existing = {(r.code, r.trade_date): r for r in existing_rows}

    inserted = 0
    updated = 0
    update_fields = ("open", "high", "low", "close", "volume", "amount", "turnover", "pe", "pb")
    for key, r in deduped.items():
        row = existing.get(key)
        if row is None:
            db.add(StockDaily(
                code=r["code"],
                trade_date=r["trade_date"],
                open=r.get("open"),
                high=r.get("high"),
                low=r.get("low"),
                close=r.get("close"),
                volume=r.get("volume"),
                amount=r.get("amount"),
                turnover=r.get("turnover"),
                pe=r.get("pe"),
                pb=r.get("pb"),
            ))
            inserted += 1
            continue
        for field in update_fields:
            value = r.get(field)
            if value is not None:
                setattr(row, field, value)
        updated += 1

    db.commit()
    return inserted, updated


def _sync_daily_bs_parallel(
    db: Session,
    codes: list[str],
    start_date: str | None,
    end_date: str | None,
    *,
    full_market_request: bool,
    workers: int = BAOSTOCK_SYNC_WORKERS,
) -> int:
    """Sequoia-X-style multi-process baostock sync for large code lists.

    Use small chunks and commit each completed chunk immediately. A slow
    upstream request must not hold all successfully fetched rows in memory
    until the entire market finishes.
    """
    from multiprocessing import Pool, TimeoutError as MpTimeoutError

    if len(codes) < 100:
        return -1

    n_workers = max(1, min(workers, len(codes)))
    chunk_size = 100
    chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]
    logger.info(
        "[BS-DAILY-MP] {} 只, workers={}, batches={}, 日期 {} → {}",
        len(codes), n_workers, len(chunks), start_date, end_date,
    )

    inserted = 0
    updated = 0
    raw_rows = 0
    failed = 0
    errors: list[str] = []
    try:
        with Pool(n_workers) as pool:
            tasks = [(chunk, start_date, end_date) for chunk in chunks]
            iterator = pool.imap_unordered(_fetch_kline_chunk_worker, tasks)
            for index in range(1, len(tasks) + 1):
                try:
                    result = iterator.next(timeout=BAOSTOCK_BATCH_TIMEOUT)
                except MpTimeoutError:
                    logger.warning(
                        "[BS-DAILY-MP] 等待批次超过 {} 秒，终止剩余 worker；已完成 {}/{} 批",
                        BAOSTOCK_BATCH_TIMEOUT, index - 1, len(tasks),
                    )
                    pool.terminate()
                    break
                rows = result.get("rows") or []
                raw_rows += len(rows)
                failed += int(result.get("failed") or 0)
                if result.get("error"):
                    errors.append(result["error"])
                chunk_inserted, chunk_updated = _upsert_daily_rows(db, rows)
                inserted += chunk_inserted
                updated += chunk_updated
                if index % 5 == 0 or index == len(chunks):
                    logger.info(
                        "[BS-DAILY-MP] 进度 {}/{}: 新增 {} / 更新 {} / 失败股票 {}",
                        index, len(chunks), inserted, updated, failed,
                    )
    except Exception as exc:
        logger.warning("[BS-DAILY-MP] 多进程拉取异常: {}", str(exc)[:160])

    if errors:
        for msg in errors[:3]:
            logger.warning("[BS-DAILY-MP] worker 失败: {}", msg)

    if raw_rows == 0:
        logger.warning("[BS-DAILY-MP] 未拉到任何行，失败股票数 {}", failed)
        if full_market_request:
            inserted = sync_daily_sina(db)
            try:
                inserted += sync_full_valuation_tx(db)
            except Exception as tx_exc:
                logger.warning("[BS-DAILY-MP] TX valuation fallback 失败: {}", str(tx_exc)[:120])
            try:
                inserted += sync_full_valuation_em(db)
            except Exception as em_exc:
                logger.warning("[BS-DAILY-MP] EM valuation fallback 失败: {}", str(em_exc)[:120])
            return inserted
        return 0

    logger.info(
        "[BS-DAILY-MP] 完成: 新增 {} / 更新 {} / worker 失败股票 {} / 原始行 {}",
        inserted, updated, failed, raw_rows,
    )
    return inserted + updated


def sync_daily_bs(
    db: Session,
    codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    days_back: int = 5,
) -> int:
    """baostock 全市场/指定池日线写入 stock_daily。

    参数：
    - codes: 如果为 None，则从 stock_basic 拿全部代码
    - start_date / end_date: 日期范围。若都不传则默认拉最近 days_back 个自然日
    - days_back: 默认最近 5 个自然日（覆盖周末/节假日）

    每只股票一次 bs 查询，全量 upsert 入 stock_daily。
    5000 只约需 30-40 分钟（单 session，逐步 sleep）。
    """
    full_market_request = codes is None
    if codes is None:
        codes = [c for (c,) in db.query(StockBasic.code).all()]
    if not codes:
        logger.warning("[BS-DAILY] 没有可同步的股票代码")
        return 0

    if not start_date and not end_date:
        end = date.today()
        from datetime import timedelta
        start = end - timedelta(days=days_back)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")

    logger.info("[BS-DAILY] {} 只, 日期 {} → {}", len(codes), start_date or "最早", end_date or "今天")

    parallel_result = _sync_daily_bs_parallel(
        db,
        codes,
        start_date,
        end_date,
        full_market_request=full_market_request,
    )
    if parallel_result >= 0:
        return parallel_result

    total_inserted = 0
    total_updated = 0
    failed = 0

    try:
        _ensure_login()
    except Exception as e:
        logger.warning("[BS-DAILY] baostock 登录失败，切换 AKShare fallback: {}", str(e)[:120])
        if full_market_request:
            inserted = sync_daily_sina(db)
            try:
                inserted += sync_full_valuation_tx(db)
            except Exception as tx_exc:
                logger.warning("[BS-DAILY] TX valuation fallback 失败: {}", str(tx_exc)[:120])
            try:
                inserted += sync_full_valuation_em(db)
            except Exception as em_exc:
                logger.warning("[BS-DAILY] EM valuation fallback 失败: {}", str(em_exc)[:120])
            return inserted
        if len(codes) <= 30:
            fallback_inserted = 0
            for code in codes:
                fallback_inserted += backfill_kline_single(db, code, days_back)
            return fallback_inserted
        logger.warning("[BS-DAILY] 指定代码过多且 baostock 不可用，跳过本次历史回填")
        return 0

    try:
        for i, code in enumerate(codes):
            try:
                klines = fetch_kline_unsafe(code, start_date, end_date)
                if not klines:
                    failed += 1
                    continue

                have_dates = {
                    r[0] for r in db.query(StockDaily.trade_date)
                    .filter(StockDaily.code == code).all()
                }
                for r in klines:
                    td = r["trade_date"]
                    if td in have_dates:
                        # 更新已有行
                        existing = db.query(StockDaily).filter(
                            StockDaily.code == code,
                            StockDaily.trade_date == td,
                        ).first()
                        if existing:
                            for fld in ("open", "high", "low", "close", "volume", "amount", "turnover", "pe", "pb"):
                                v = r.get(fld)
                                if v is not None:
                                    setattr(existing, fld, v)
                            total_updated += 1
                        continue

                    db.add(StockDaily(
                        code=code, trade_date=td,
                        open=r.get("open"), high=r.get("high"),
                        low=r.get("low"), close=r.get("close"),
                        volume=r.get("volume"), amount=r.get("amount"),
                        turnover=r.get("turnover"),
                        pe=r.get("pe"), pb=r.get("pb"),
                    ))
                    total_inserted += 1

                if i % 100 == 0 and i > 0:
                    db.commit()
                    logger.info("[BS-DAILY] 进度 {}/{} 已写入 {}/更新 {}",
                                i, len(codes), total_inserted, total_updated)

            except Exception as e:
                failed += 1
                if failed <= 5:
                    logger.warning("[BS-DAILY] {} 失败: {}", code, str(e)[:80])

            if i > 0 and i % 20 == 0:
                time.sleep(0.3)

        db.commit()
    finally:
        _ensure_logout()

    logger.info("[BS-DAILY] 完成: 新增 {} / 更新 {} / 失败 {}",
                total_inserted, total_updated, failed)
    return total_inserted + total_updated


def sync_kline_bs(db: Session, code: str, days: int) -> int:
    """baostock 单只股票 K 线回填（被 API 懒加载调用）。
    只拉最近 days*2 个自然日的数据，upsert 到 stock_daily。

    前复权价格会随分红送转变化，因此不能只插入缺失行。已有行也必须覆盖，
    否则同一窗口内会混入不同复权基准，造成 K 线断层和策略假突破。
    """
    from datetime import timedelta
    end = date.today()
    start = end - timedelta(days=max(days * 2, 60))

    klines = fetch_kline(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if not klines:
        return 0

    inserted, updated = _upsert_daily_rows(db, klines)
    logger.info("[BS-KLINE] {} 新增 {} / 更新 {}", code, inserted, updated)
    return inserted + updated


def sync_financial_bs(
    db: Session,
    pool: str = "csi300",
) -> int:
    """baostock 拉全市场/指定池财务指标写入 stock_financial。

    pool 可选: "csi300" (默认), "csi500", "all" (全部 A 股)
    """
    if pool == "all":
        codes = [c for (c,) in db.query(StockBasic.code).all()]
    elif pool in ("csi300", "csi500"):
        # 从 stock_basic 中取前 N 只（或全部如果不足）
        codes = [c for (c,) in db.query(StockBasic.code).limit(
            300 if pool == "csi300" else 500
        ).all()]
    else:
        codes = [pool]  # 单个代码

    if not codes:
        logger.warning("[BS-FIN] 无可用代码")
        return 0

    logger.info("[BS-FIN] {} 只", len(codes))
    fin_data = fetch_financial_batch(codes)
    inserted = 0
    updated = 0

    for code, fin in fin_data.items():
        try:
            # 用当前年份 Q4 作为报告期
            now = date.today()
            report_date = date(now.year - 1, 12, 31) if now.month < 4 else date(now.year, 3, 31)
            # 更稳健：取 2024Q4 或当前可用的最新季度
            existing = db.query(StockFinancial).filter(
                StockFinancial.code == code,
            ).order_by(StockFinancial.report_date.desc()).first()

            if existing and existing.report_date >= date(2024, 12, 31):
                # 已有最新数据，只更新 null 字段
                for fld in ("roe", "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio", "net_profit", "revenue"):
                    v = fin.get(fld)
                    if v is not None and getattr(existing, fld) is None:
                        setattr(existing, fld, v)
                updated += 1
                continue

            row = StockFinancial(
                code=code,
                report_date=date(2024, 12, 31),
                roe=fin.get("roe"),
                revenue_yoy=fin.get("revenue_yoy"),
                profit_yoy=fin.get("profit_yoy"),
                gross_margin=fin.get("gross_margin"),
                debt_ratio=fin.get("debt_ratio"),
                net_profit=fin.get("net_profit"),
                revenue=fin.get("revenue"),
            )
            db.add(row)
            inserted += 1
        except Exception as e:
            logger.warning("[BS-FIN] {} 写入失败: {}", code, str(e)[:80])

    db.commit()
    logger.info("[BS-FIN] 完成: 新增 {} / 更新 {}", inserted, updated)
    return inserted + updated


def refresh_dividend_yield_bs(
    db: Session,
    as_of: date | None = None,
    codes: list[str] | None = None,
) -> int:
    """用本地现金分红记录快速重算最新交易日的近 12 个月股息率。"""
    trade_date = as_of or db.query(func.max(StockDaily.trade_date)).scalar()
    if trade_date is None:
        logger.warning("[BS-DIVIDEND] 没有日行情，跳过股息率重算")
        return 0
    if db.query(StockDividend.id).first() is None:
        logger.warning("[BS-DIVIDEND] 本地分红记录为空，跳过股息率重算")
        return 0

    start_date = trade_date - timedelta(days=365)
    cash_rows = (
        db.query(StockDividend.code, func.sum(StockDividend.cash_per_share))
        .filter(
            StockDividend.operate_date > start_date,
            StockDividend.operate_date <= trade_date,
        )
        .group_by(StockDividend.code)
        .all()
    )
    cash_by_code = {code: float(cash or 0) for code, cash in cash_rows}
    daily_query = db.query(StockDaily).filter(StockDaily.trade_date == trade_date)
    if codes is not None:
        daily_query = daily_query.filter(StockDaily.code.in_(codes))
    daily_rows = daily_query.all()
    updated = 0
    for daily in daily_rows:
        if daily.close is None or daily.close <= 0:
            continue
        value = round(cash_by_code.get(daily.code, 0.0) / daily.close * 100, 4)
        if daily.dividend_yield != value:
            daily.dividend_yield = value
            updated += 1
    db.commit()
    logger.info("[BS-DIVIDEND] {} 本地重算完成: 更新 {}", trade_date, updated)
    return updated


def _fetch_dividend_chunk_worker(args: tuple[list[str], list[str]]) -> dict:
    """Worker used by full-market dividend sync."""
    codes, years = args
    try:
        from app.services.providers.baostock_provider import fetch_dividend_batch

        records = fetch_dividend_batch(codes, years=years)
        return {
            "records": records,
            "handled": len(codes),
            "failed": len(codes) - len(records),
            "error": None,
        }
    except Exception as exc:
        return {
            "records": {},
            "handled": len(codes),
            "failed": len(codes),
            "error": str(exc)[:160],
        }


def _fetch_dividend_records_parallel(
    codes: list[str],
    years: list[str],
    *,
    workers: int = BAOSTOCK_SYNC_WORKERS,
) -> dict[str, list[dict]]:
    """Pull dividends with bounded process workers and keep partial results."""
    from multiprocessing import Pool, TimeoutError as MpTimeoutError

    if len(codes) < 100:
        return fetch_dividend_batch(codes, years=years)

    n_workers = max(1, min(workers, len(codes)))
    chunk_size = 100
    chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]
    records: dict[str, list[dict]] = {}
    failed = 0
    logger.info("[BS-DIVIDEND-MP] {} 只, workers={}, batches={}", len(codes), n_workers, len(chunks))
    with Pool(n_workers) as pool:
        iterator = pool.imap_unordered(_fetch_dividend_chunk_worker, [(chunk, years) for chunk in chunks])
        for index in range(1, len(chunks) + 1):
            try:
                result = iterator.next(timeout=BAOSTOCK_BATCH_TIMEOUT)
            except MpTimeoutError:
                logger.warning(
                    "[BS-DIVIDEND-MP] 等待批次超过 {} 秒，终止剩余 worker；已完成 {}/{} 批",
                    BAOSTOCK_BATCH_TIMEOUT, index - 1, len(chunks),
                )
                pool.terminate()
                break
            records.update(result.get("records") or {})
            failed += int(result.get("failed") or 0)
            if result.get("error"):
                logger.warning("[BS-DIVIDEND-MP] worker 失败: {}", result["error"])
            if index % 5 == 0 or index == len(chunks):
                logger.info(
                    "[BS-DIVIDEND-MP] 进度 {}/{}: 成功股票 {} / 失败股票 {}",
                    index, len(chunks), len(records), failed,
                )
    return records


def sync_dividend_yield_bs(
    db: Session,
    codes: list[str] | None = None,
    as_of: date | None = None,
) -> int:
    """从 baostock 更新分红记录，再重算最新交易日的 TTM 股息率。

    远程拉取适合每周运行。日行情同步后只调用 refresh_dividend_yield_bs，
    避免每日重复遍历全市场远程接口。
    """
    trade_date = as_of or db.query(func.max(StockDaily.trade_date)).scalar()
    if trade_date is None:
        logger.warning("[BS-DIVIDEND] 没有日行情，跳过远程同步")
        return 0
    if codes is None:
        codes = [code for (code,) in db.query(StockBasic.code).all()]
    if not codes:
        logger.warning("[BS-DIVIDEND] 没有可同步的股票代码")
        return 0

    years = [str(trade_date.year - 1), str(trade_date.year)]
    logger.info("[BS-DIVIDEND] {} 只, 年份 {}", len(codes), years)
    records = _fetch_dividend_records_parallel(codes, years=years)
    existing = {
        (row.code, row.operate_date, row.cash_per_share)
        for row in db.query(StockDividend).filter(
            StockDividend.operate_date > trade_date - timedelta(days=730),
        ).all()
    }
    inserted = 0
    last_committed = 0
    for code, rows in records.items():
        for row in rows:
            key = (code, row["operate_date"], row["cash_per_share"])
            if key in existing:
                continue
            db.add(StockDividend(code=code, **row))
            existing.add(key)
            inserted += 1
        if inserted - last_committed >= 200:
            db.commit()
            last_committed = inserted
    db.commit()
    updated = refresh_dividend_yield_bs(db, as_of=trade_date, codes=list(records))
    logger.info("[BS-DIVIDEND] 完成: 新增记录 {} / 更新股息率 {}", inserted, updated)
    return inserted + updated


def backfill_kline_single_bs(db: Session, code: str, days: int) -> int:
    """baostock 版本的单只 K 线回填 —— 与 AKShare 版同签名的替代函数。"""
    try:
        return sync_kline_bs(db, code, days)
    except Exception as e:
        logger.warning("[BS-KLINE] {} baostock 失败，切换 AKShare fallback: {}", code, str(e)[:120])
        return backfill_kline_single(db, code, days)


def backfill_kline_all_bs(db: Session, days: int = 60) -> int:
    """baostock 全市场 K 线回填，约 30-50 分钟（逐只串行）。"""
    codes = [c for (c,) in db.query(StockBasic.code).all()]
    logger.info("[BS-KLINE-ALL] {} 只, {} 天", len(codes), days)

    from datetime import timedelta
    end = date.today()
    start = end - timedelta(days=max(days * 2, 120))
    sd = start.strftime("%Y-%m-%d")
    ed = end.strftime("%Y-%m-%d")

    return sync_daily_bs(db, codes=codes, start_date=sd, end_date=ed)
